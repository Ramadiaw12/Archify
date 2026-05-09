# backend/rag.py
"""
Composants RAG (Retrieval-Augmented Generation) :
  1. TextChunker     — découpe le texte en chunks avec chevauchement
  2. EmbeddingEngine — génère les vecteurs (SentenceTransformers local)
  3. VectorStore     — stockage en mémoire + recherche par similarité cosinus

Tout est en mémoire : aucune base de données externe requise.
"""

import math
import re
from dataclasses import dataclass, field

import numpy as np

from config import settings


# ── Structures ──────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    """Un extrait de texte avec son index et son vecteur d'embedding."""
    text: str
    index: int
    embedding: list[float] = field(default_factory=list)


# ── 1. Chunker ──────────────────────────────────────────────────────────────────

class TextChunker:
    """
    Stratégie de découpage :
      - Divise d'abord par paragraphes (séparés par lignes vides)
      - Fusionne les paragraphes jusqu'à atteindre chunk_size (en mots)
      - Ajoute un chevauchement (overlap) pour conserver le contexte

    Avantage : préserve la cohérence sémantique des paragraphes.
    """

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        """
        Découpe `text` en chunks et retourne une liste de strings.

        Args:
            text: texte brut nettoyé issu du DocumentParser

        Returns:
            Liste de strings, chaque string étant un chunk cohérent
        """
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        chunks: list[str] = []
        current = ""
        current_words = 0

        for para in paragraphs:
            para_words = len(para.split())

            # Paragraphe trop long → le découper par phrases
            if para_words > self.chunk_size:
                if current:
                    chunks.append(current.strip())
                    current = ""
                    current_words = 0
                chunks.extend(self._split_by_sentences(para))
                continue

            # Ajout du paragraphe au chunk courant
            if current_words + para_words > self.chunk_size and current:
                chunks.append(current.strip())
                # Overlap : reprendre les derniers mots du chunk précédent
                overlap_words = current.split()[-self.overlap:]
                current = " ".join(overlap_words) + "\n\n" + para
                current_words = len(current.split())
            else:
                current = (current + "\n\n" + para).strip()
                current_words += para_words

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def _split_by_sentences(self, text: str) -> list[str]:
        """Découpe un texte long en chunks au niveau des phrases."""
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


# ── 2. Embedding Engine ─────────────────────────────────────────────────────────

class EmbeddingEngine:
    """
    Génère des vecteurs denses via SentenceTransformers (modèle local).
    Fallback automatique vers TF-IDF si la bibliothèque n'est pas disponible.

    Le modèle est chargé une seule fois (lazy loading).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None          # Chargé à la première utilisation
        self._use_fallback = False

    def _load(self) -> None:
        """Charge SentenceTransformer ou active le fallback TF-IDF."""
        if self._model is not None or self._use_fallback:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        except Exception:
            self._use_fallback = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Retourne une liste de vecteurs (un par texte).

        Args:
            texts: liste de chaînes à encoder

        Returns:
            Liste de listes de floats (vecteurs normalisés L2)
        """
        self._load()
        if self._use_fallback:
            return self._tfidf(texts)

        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]

    # ── Fallback TF-IDF ────────────────────────────────────────────────────────

    def _tfidf(self, texts: list[str]) -> list[list[float]]:
        """
        Implémentation TF-IDF minimaliste, sans dépendance externe.
        Utilisé uniquement si sentence-transformers est absent.
        """
        # Tokenisation simple
        tokenized = [re.findall(r"\b\w+\b", t.lower()) for t in texts]
        vocab = sorted({w for toks in tokenized for w in toks})
        vocab_idx = {w: i for i, w in enumerate(vocab)}
        n_docs = len(texts)

        # IDF (lissage +1)
        idf = {}
        for w in vocab:
            df = sum(1 for toks in tokenized if w in toks)
            idf[w] = math.log((n_docs + 1) / (df + 1)) + 1.0

        # TF-IDF + normalisation L2
        vectors: list[list[float]] = []
        for toks in tokenized:
            vec = [0.0] * len(vocab)
            if not toks:
                vectors.append(vec)
                continue
            tf: dict[str, float] = {}
            for w in toks:
                tf[w] = tf.get(w, 0) + 1 / len(toks)
            for w, tf_val in tf.items():
                if w in vocab_idx:
                    vec[vocab_idx[w]] = tf_val * idf[w]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])
        return vectors


# ── 3. Vector Store en mémoire ──────────────────────────────────────────────────

class VectorStore:
    """
    Stockage de chunks et recherche par similarité cosinus.
    Entièrement en mémoire — aucun fichier ou base de données.

    Complexité : O(n) par recherche, suffisant pour des documents < 100 pages.
    """

    def __init__(self):
        self._chunks: list[Chunk] = []

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """Ajoute des chunks au store."""
        self._chunks.extend(chunks)

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[Chunk]:
        """
        Retourne les `top_k` chunks les plus similaires à `query_embedding`.

        Args:
            query_embedding: vecteur de la requête (même dimension que les chunks)
            top_k: nombre de résultats à retourner

        Returns:
            Liste de Chunks triés par score décroissant
        """
        if not self._chunks:
            return []

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)

        scored: list[tuple[float, Chunk]] = []
        for chunk in self._chunks:
            if not chunk.embedding:
                continue
            c = np.array(chunk.embedding, dtype=np.float32)
            denom = q_norm * np.linalg.norm(c)
            score = float(np.dot(q, c) / denom) if denom > 1e-9 else 0.0
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def clear(self) -> None:
        """Vide le store (utilisé entre deux documents)."""
        self._chunks.clear()