# backend/document_service.py
"""
Service de gestion des documents et du chat.

Fonctions :
  - store_document     : stocke texte + chunks + embeddings en DB
  - get_documents      : liste des documents d'un user
  - get_document       : récupère un document avec ses chunks
  - delete_document    : supprime un document
  - ask_document       : pose une question sur un document (RAG + Groq)
  - get_chat_history   : récupère l'historique d'un chat
"""

import os
import json
import logging
import numpy as np
from datetime import datetime, timezone

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from db.models import Document, DocumentChunk, Chat, ChatMessage
from rag import TextChunker, RAGEngine
from config import settings

logger = logging.getLogger(__name__)

chunker    = TextChunker(chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
rag_engine = RAGEngine()


# Stocker un document 

async def store_document(
    db:        AsyncSession,
    user_id:   str,
    filename:  str,
    file_type: str,
    raw_text:  str,
    word_count: int,
    page_count: int,
) -> Document:
    """
    Stocke un document en DB avec ses chunks et embeddings.
    Le fichier original n'est jamais conservé — seulement le texte.
    """
    # Créer le document
    doc = Document(
        user_id    = user_id,
        filename   = filename,
        file_type  = file_type,
        raw_text   = raw_text,
        word_count = word_count,
        page_count = page_count,
    )
    db.add(doc)
    await db.flush()   # obtenir l'ID sans commit

    # Chunker le texte
    chunks = chunker.chunk(raw_text)

    # Générer les embeddings
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(settings.embedding_model)
        embeddings = model.encode(chunks, normalize_embeddings=True).tolist()
    except Exception as e:
        logger.warning(f"Embeddings échoués : {e} — chunks sans embeddings")
        embeddings = [None] * len(chunks)

    # Stocker les chunks
    for i, (text, emb) in enumerate(zip(chunks, embeddings)):
        chunk = DocumentChunk(
            document_id = doc.id,
            chunk_index = i,
            text        = text,
            embedding   = emb,
        )
        db.add(chunk)

    await db.commit()
    await db.refresh(doc)
    logger.info(f"Document stocké : {filename} ({len(chunks)} chunks) pour user {user_id}")
    return doc


# Liste des documents 

async def get_documents(
    db:       AsyncSession,
    user_id:  str,
    page:     int = 1,
    per_page: int = 20,
) -> dict:
    """Retourne la liste paginée des documents d'un utilisateur."""
    offset = (page - 1) * per_page

    rows = await db.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(desc(Document.created_at))
        .offset(offset)
        .limit(per_page)
    )
    docs = rows.scalars().all()

    count = await db.execute(
        select(func.count()).select_from(Document).where(Document.user_id == user_id)
    )
    total = count.scalar_one()

    return {
        "items": [
            {
                "id":         d.id,
                "filename":   d.filename,
                "file_type":  d.file_type,
                "word_count": d.word_count,
                "page_count": d.page_count,
                "created_at": d.created_at.isoformat(),
                "preview":    d.raw_text[:200] + "..." if len(d.raw_text) > 200 else d.raw_text,
            }
            for d in docs
        ],
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    max(1, -(-total // per_page)),
    }


# Récupérer un document 

async def get_document(
    db:          AsyncSession,
    document_id: str,
    user_id:     str,
) -> Document:
    """Récupère un document avec vérification d'appartenance."""
    row = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .where(Document.user_id == user_id)
    )
    doc = row.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    return doc


# Supprimer un document 

async def delete_document(
    db:          AsyncSession,
    document_id: str,
    user_id:     str,
) -> None:
    """Supprime un document et toutes ses données liées."""
    doc = await get_document(db, document_id, user_id)
    await db.delete(doc)
    await db.commit()
    logger.info(f"Document supprimé : {document_id}")


#  RAG depuis la DB 

async def _retrieve_from_db(
    db:          AsyncSession,
    document_id: str,
    query:       str,
    top_k:       int = 5,
) -> str:
    """
    Récupère les chunks les plus pertinents depuis la DB.
    Utilise les embeddings stockés pour la recherche cosinus.
    """
    rows = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = rows.scalars().all()

    if not chunks:
        return ""

    # Chunks sans embeddings → retourner les premiers
    if not chunks[0].embedding:
        texts = [c.text for c in chunks[:top_k]]
        return "\n\n---\n\n".join(f"[Extrait {i+1}]\n{t}" for i, t in enumerate(texts))

    try:
        from sentence_transformers import SentenceTransformer
        model     = SentenceTransformer(settings.embedding_model)
        query_emb = model.encode([query], normalize_embeddings=True)[0]

        # Calcul similarité cosinus
        scores = []
        for chunk in chunks:
            if chunk.embedding:
                c_emb  = np.array(chunk.embedding)
                score  = float(np.dot(query_emb, c_emb))
                scores.append((score, chunk))

        scores.sort(key=lambda x: x[0], reverse=True)
        top = [c for _, c in scores[:top_k]]
    except Exception:
        top = chunks[:top_k]

    return "\n\n---\n\n".join(
        f"[Extrait {i+1}]\n{c.text}" for i, c in enumerate(top)
    )


# Poser une question sur un document 

async def ask_document(
    db:          AsyncSession,
    document_id: str,
    user_id:     str,
    question:    str,
    chat_id:     str | None = None,
    language:    str = "fr",
) -> dict:
    """
    Pose une question sur un document stocké.
    Utilise RAG (chunks depuis DB) + Groq pour répondre.
    Sauvegarde la question et la réponse dans l'historique.
    """
    doc = await get_document(db, document_id, user_id)

    # Récupérer ou créer un chat
    if chat_id:
        chat_row = await db.execute(
            select(Chat)
            .where(Chat.id == chat_id)
            .where(Chat.user_id == user_id)
        )
        chat = chat_row.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat introuvable.")
    else:
        chat = Chat(
            document_id = document_id,
            user_id     = user_id,
            title       = question[:60] + "..." if len(question) > 60 else question,
        )
        db.add(chat)
        await db.flush()

    # Récupérer le contexte RAG
    context = await _retrieve_from_db(db, document_id, question, top_k=5)

    # Récupérer l'historique du chat (5 derniers messages)
    history_rows = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat.id)
        .order_by(desc(ChatMessage.created_at))
        .limit(10)
    )
    history = list(reversed(history_rows.scalars().all()))

    # Construire les messages pour Groq
    lang_map   = {"fr": "français", "en": "anglais", "ar": "arabe", "es": "espagnol"}
    lang_label = lang_map.get(language, "français")

    system_prompt = f"""Tu es un assistant expert en analyse documentaire.
Tu réponds aux questions sur le document "{doc.filename}" en te basant UNIQUEMENT sur son contenu.
Réponds TOUJOURS en {lang_label}.
Si la réponse n'est pas dans le document, dis-le clairement.
Sois précis, clair et concis."""

    messages = [{"role": "system", "content": system_prompt}]

    # Ajouter l'historique
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    # Ajouter le contexte RAG + la question
    user_message = f"""Contexte du document :
{context}

Question : {question}"""

    messages.append({"role": "user", "content": user_message})

    # Appel Groq
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=messages,
        temperature=0.3,
        max_tokens=1024,
    )
    answer = response.choices[0].message.content or ""

    # Sauvegarder question + réponse
    db.add(ChatMessage(chat_id=chat.id, role="user",      content=question))
    db.add(ChatMessage(chat_id=chat.id, role="assistant", content=answer))
    await db.commit()

    return {
        "chat_id":     chat.id,
        "question":    question,
        "answer":      answer,
        "document_id": document_id,
        "filename":    doc.filename,
    }


# Historique d'un chat 

async def get_chat_history(
    db:      AsyncSession,
    chat_id: str,
    user_id: str,
) -> dict:
    """Récupère l'historique complet d'un chat."""
    chat_row = await db.execute(
        select(Chat)
        .where(Chat.id == chat_id)
        .where(Chat.user_id == user_id)
    )
    chat = chat_row.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat introuvable.")

    msgs_row = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.created_at)
    )
    messages = msgs_row.scalars().all()

    return {
        "chat_id":     chat.id,
        "document_id": chat.document_id,
        "title":       chat.title,
        "created_at":  chat.created_at.isoformat(),
        "messages": [
            {
                "id":         m.id,
                "role":       m.role,
                "content":    m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


# Liste des chats d'un document 

async def get_document_chats(
    db:          AsyncSession,
    document_id: str,
    user_id:     str,
) -> list:
    """Retourne tous les chats d'un document."""
    rows = await db.execute(
        select(Chat)
        .where(Chat.document_id == document_id)
        .where(Chat.user_id == user_id)
        .order_by(desc(Chat.created_at))
    )
    chats = rows.scalars().all()
    return [
        {
            "id":         c.id,
            "title":      c.title,
            "created_at": c.created_at.isoformat(),
        }
        for c in chats
    ]