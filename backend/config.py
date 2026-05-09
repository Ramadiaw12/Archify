# backend/config.py
"""
Configuration centralisée via pydantic-settings.
Lit automatiquement les variables depuis .env ou l'environnement système.

LLM utilisé : Groq (llama3 / mixtral) — PAS Anthropic, PAS xAI.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Toutes les variables de configuration de l'application.
    Ordre de priorité : variables d'env > fichier .env > valeurs par défaut.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Clé API ───────────────────────────────────────────────────────────
    # Groq — LLM principal ET pré-traitement
    # Obtenir sur : https://console.groq.com/
    groq_api_key: str = ""

    # ── Modèles Groq ──────────────────────────────────────────────────────
    # Modèle principal pour la génération du résumé (puissant)
    groq_model_main: str = "llama3-70b-8192"

    # Modèle rapide pour la pré-classification du document
    groq_model_fast: str = "llama3-8b-8192"

    # ── Embedding ─────────────────────────────────────────────────────────
    # Modèle local — aucune API requise, tourne sur votre machine
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── RAG ───────────────────────────────────────────────────────────────
    chunk_size: int = 800        # Taille cible d'un chunk (en mots)
    chunk_overlap: int = 100     # Chevauchement entre deux chunks consécutifs
    top_k_chunks: int = 5        # Nombre de chunks retournés par le retriever

    # ── Serveur ───────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Upload & Sécurité ─────────────────────────────────────────────────
    max_file_size_mb: int = 20
    allowed_extensions: list[str] = [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"]
    upload_dir: str = "/tmp/docsummarizer"
    # Supprimer le fichier immédiatement après traitement (confidentialité)
    delete_after_processing: bool = True


# Singleton importé dans tous les modules de l'app
settings = Settings()