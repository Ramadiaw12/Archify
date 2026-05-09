# backend/rag.py
"""
Composants RAG (Retrieval-Augmented Generation) :
  1. TextChunker     — découpe le texte en chunks avec chevauchement
  2. EmbeddingEngine — génère les vecteurs (SentenceTransformers local)
                       fallback TF-IDF corrigé : même vocabulaire pour chunks ET requête
  3. VectorStore     — stockage en mémoire + recherche par similarité cosinus

CORRECTION BUG "shapes not aligned" :
  L'ancien code construisait un vocabulaire différent pour les chunks (gros corpus)
  et pour la requête (petit texte) → dimensions incompatibles ex: (362,) vs (83,).
  Fix : embed_with_query() encode chunks + requête en un seul appel,
  avec le même vocabulaire partagé.
"""

import math
import re
from dataclasses import dataclass, field

import numpy as np

from config import settings


# ── Structure de données ─────────────────────────────────────────────────────

@dataclass
class Chunk:
    """Un extrait de texte avec son index et son vecteur d'embedding."""
    text: str
    index: int
    embedding: list[float] = field(default_factory=list)


# ── 1. Chunker ───────────────────────────────────────────────────────────────

class TextChunker:
    """
    Découpe un texte en chunks cohérents avec chevauchement (overlap).

    Stratégie :
      1. Divise par paragraphes (lignes vides)
      2. Fusionne jusqu'à chunk_size mots
      3. Ajoute overlap mots de chevauchement entre chunks consécutifs
    """

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        """Retourne une liste de strings (chunks)."""
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        chunks: list[str] = []
        current = ""
        current_words = 0

        for para in paragraphs:
            para_words = len(para.split())

            if para_words > self.chunk_size:
                if current:
                    chunks.append(current.strip())
                    current = ""
                    current_words = 0
                chunks.extend(self._split_sentences(para))
                continue

            if current_words + para_words > self.chunk_size and current:
                chunks.append(current.strip())
                overlap_words = current.split()[-self.overlap:]
                current = " ".join(overlap_words) + "\n\n" + para
                current_words = len(current.split())
            else:
                current = (current + "\n\n" + para).strip()
                current_words += para_words

        if current.strip():
            chunks.append(current.strip())

        # Garantir au moins un chunk
        return chunks if chunks else [text[:3000]]

    def _split_sentences(self, text: str) -> list[str]:
        """Découpe un paragraphe long par phrases."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        current_words = 0

        for sent in sentences:
            sent_words = len(sent.split())
            if current_words + sent_words > self.chunk_size and current:
                chunks.append(current.strip())
                overlap_words = current.split()[-self.overlap:]
                current = " ".join(overlap_words) + " " + sent
                current_words = len(current.split())
            else:
                current = (current + " " + sent).strip()
                current_words += sent_words

        if current.strip():
            chunks.append(current.strip())
        return chunks


# ── 2. Embedding Engine ──────────────────────────────────────────────────────

class EmbeddingEngine:
    """
    Génère des vecteurs denses pour les textes.

    Mode 1 — SentenceTransformers (préféré) :
      Vecteurs de dimension fixe 384 (all-MiniLM-L6-v2).
      Pas de problème de dimension.

    Mode 2 — TF-IDF (fallback si sentence-transformers absent) :
      IMPORTANT : la méthode embed_with_query() DOIT être utilisée
      pour encoder chunks + requête ensemble, garantissant le même
      vocabulaire et donc la même dimension vectorielle.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._use_fallback = False
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        except Exception:
            self._use_fallback = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Encode une liste de textes. Tous partagent le même espace vectoriel.
        Pour le RAG, préférer embed_with_query() qui est plus explicite.
        """
        self._load()
        if not texts:
            return []
        if self._use_fallback:
            return self._tfidf_batch(texts)
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [e.tolist() for e in embeddings]

    def embed_with_query(
        self,
        chunk_texts: list[str],
        query: str,
    ) -> tuple[list[list[float]], list[float]]:
        """
        ✅ Méthode correcte pour le RAG.

        Encode les chunks ET la requête en un seul appel,
        garantissant que tous les vecteurs ont la même dimension.

        Args:
            chunk_texts : textes des chunks du document
            query       : texte de la requête de retrieval

        Returns:
            (liste d'embeddings des chunks, embedding de la requête)
        """
        all_texts = chunk_texts + [query]
        all_embeddings = self.embed(all_texts)
        return all_embeddings[:-1], all_embeddings[-1]

    def _tfidf_batch(self, texts: list[str]) -> list[list[float]]:
        """
        TF-IDF sur un batch. Le vocabulaire est construit sur TOUS les textes
        du batch ensemble → même dimension pour chaque vecteur.
        """
        tokenized = [re.findall(r"\b\w+\b", t.lower()) for t in texts]
        vocab = sorted({w for toks in tokenized for w in toks})
        vocab_idx = {w: i for i, w in enumerate(vocab)}
        n = len(vocab)
        n_docs = len(texts)

        if n == 0:
            return [[0.0] for _ in texts]

        # IDF
        idf: dict[str, float] = {}
        for w in vocab:
            df = sum(1 for toks in tokenized if w in toks)
            idf[w] = math.log((n_docs + 1) / (df + 1)) + 1.0

        # TF-IDF + normalisation L2
        vectors: list[list[float]] = []
        for toks in tokenized:
            vec = [0.0] * n
            if not toks:
                vectors.append(vec)
                continue
            tf: dict[str, float] = {}
            for w in toks:
                tf[w] = tf.get(w, 0) + 1.0 / len(toks)
            for w, tf_val in tf.items():
                if w in vocab_idx:
                    vec[vocab_idx[w]] = tf_val * idf[w]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])

        return vectors


# ── 3. Vector Store en mémoire ───────────────────────────────────────────────

class VectorStore:
    """
    Stockage et recherche de Chunks par similarité cosinus.
    Entièrement en mémoire.
    """

    def __init__(self):
        self._chunks: list[Chunk] = []

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self._chunks.extend(chunks)

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[Chunk]:
        """
        Retourne les top_k chunks les plus proches (similarité cosinus).

        Les dimensions de query_embedding et des embeddings des chunks
        doivent être identiques — garanti par embed_with_query().
        """
        if not self._chunks:
            return []

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)

        # Requête nulle → retourner les premiers chunks
        if q_norm < 1e-9:
            return self._chunks[:top_k]

        scored: list[tuple[float, Chunk]] = []
        for chunk in self._chunks:
            if not chunk.embedding:
                continue
            c = np.array(chunk.embedding, dtype=np.float32)

            # Garde-fou contre les dimensions incompatibles
            if c.shape != q.shape:
                continue

            c_norm = np.linalg.norm(c)
            denom = q_norm * c_norm
            score = float(np.dot(q, c) / denom) if denom > 1e-9 else 0.0
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def clear(self) -> None:
        self._chunks.clear()