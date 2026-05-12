# backend/rag.py
"""
Pipeline RAG — chromadb + langchain-community + sentence-transformers
"""

import re
import uuid
import logging
from dataclasses import dataclass

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    text:  str
    index: int


class TextChunker:
    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap    = overlap

    def chunk(self, text: str) -> list[str]:
        paragraphs    = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        chunks        = []
        current       = ""
        current_words = 0

        for para in paragraphs:
            para_words = len(para.split())
            if para_words > self.chunk_size:
                if current:
                    chunks.append(current.strip())
                    current, current_words = "", 0
                chunks.extend(self._split_sentences(para))
                continue
            if current_words + para_words > self.chunk_size and current:
                chunks.append(current.strip())
                overlap_words = current.split()[-self.overlap:]
                current       = " ".join(overlap_words) + "\n\n" + para
                current_words = len(current.split())
            else:
                current       = (current + "\n\n" + para).strip()
                current_words += para_words

        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[:3000]]

    def _split_sentences(self, text: str) -> list[str]:
        sentences     = re.split(r"(?<=[.!?])\s+", text)
        chunks        = []
        current       = ""
        current_words = 0
        for sent in sentences:
            sent_words = len(sent.split())
            if current_words + sent_words > self.chunk_size and current:
                chunks.append(current.strip())
                current       = " ".join(current.split()[-self.overlap:]) + " " + sent
                current_words = len(current.split())
            else:
                current       = (current + " " + sent).strip()
                current_words += sent_words
        if current.strip():
            chunks.append(current.strip())
        return chunks


class RAGEngine:
    def __init__(self):
        self._embeddings = None

    def _get_embeddings(self):
        if self._embeddings is None:
            try:
                from langchain_community.embeddings import SentenceTransformerEmbeddings
                self._embeddings = SentenceTransformerEmbeddings(model_name=settings.embedding_model)
            except Exception:
                from sentence_transformers import SentenceTransformer
                self._embeddings = _STWrapper(SentenceTransformer(settings.embedding_model))
        return self._embeddings

    def retrieve(self, chunks: list[str], top_k: int = 5) -> tuple[list[Chunk], str]:
        if not chunks:
            return [], ""
        try:
            import chromadb
            from langchain_community.vectorstores import Chroma

            client      = chromadb.EphemeralClient()
            vectorstore = Chroma.from_texts(
                texts=chunks,
                embedding=self._get_embeddings(),
                client=client,
                collection_name=f"doc_{uuid.uuid4().hex[:8]}",
                metadatas=[{"index": i} for i in range(len(chunks))],
            )
            auto_query  = " ".join(" ".join(chunks).split()[:150])
            results     = vectorstore.similarity_search(auto_query, k=min(top_k, len(chunks)))
            top_chunks  = [Chunk(text=d.page_content, index=d.metadata.get("index", i)) for i, d in enumerate(results)]
            context     = "\n\n---\n\n".join(f"[Extrait {c.index+1}]\n{c.text}" for c in top_chunks)
            return top_chunks, context
        except Exception as e:
            logger.error(f"ChromaDB échoué : {e} — fallback")
            return self._fallback(chunks, top_k)

    def _fallback(self, chunks: list[str], top_k: int) -> tuple[list[Chunk], str]:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        model      = SentenceTransformer(settings.embedding_model)
        all_embs   = model.encode(chunks + [" ".join(" ".join(chunks).split()[:150])], normalize_embeddings=True)
        query_emb  = all_embs[-1]
        scores     = [float(np.dot(query_emb, e)) for e in all_embs[:-1]]
        top_idx    = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        top_chunks = [Chunk(text=chunks[i], index=i) for i in top_idx]
        context    = "\n\n---\n\n".join(f"[Extrait {c.index+1}]\n{c.text}" for c in top_chunks)
        return top_chunks, context


class _STWrapper:
    def __init__(self, model): self._model = model
    def embed_documents(self, texts): return self._model.encode(texts, normalize_embeddings=True).tolist()
    def embed_query(self, text): return self._model.encode([text], normalize_embeddings=True)[0].tolist()


chunker    = TextChunker(chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
rag_engine = RAGEngine()