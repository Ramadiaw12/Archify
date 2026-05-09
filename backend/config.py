# backend/config.py
"""
Configuration de l'application — lue depuis le fichier .env
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Clé API Groq ──────────────────────────────────────────────────────────
    groq_api_key: str = ""

    # ── Modèle Groq — défini dans votre .env ─────────────────────────────────
    # Mettez le nom exact du modèle affiché dans votre console Groq
    groq_model: str = "mixtral-8x7b-32768"

    # ── Embedding local (aucune API requise) ──────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── RAG ───────────────────────────────────────────────────────────────────
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k_chunks: int = 5

    # ── Serveur ───────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Upload ────────────────────────────────────────────────────────────────
    max_file_size_mb: int = 20
    allowed_extensions: list[str] = [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"]
    upload_dir: str = "/tmp/docsummarizer"
    delete_after_processing: bool = True


settings = Settings()