# backend/config.py
"""
Configuration centralisée via pydantic-settings.
Lit automatiquement les variables depuis .env ou l'environnement système.
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

    # ── Clés API ──────────────────────────────────────────────────────────
    anthropic_api_key: str = ""   # Claude — LLM principal
    groq_api_key: str = ""        # Groq / LLaMA — pré-traitement optionnel

    # ── Modèles ───────────────────────────────────────────────────────────
    claude_model: str = "claude-3-5-sonnet-20241022"
    groq_model: str = "llama3-8b-8192"
    embedding_model: str = "all-MiniLM-L6-v2"   # Local, aucune API requise

    # ── RAG ───────────────────────────────────────────────────────────────
    chunk_size: int = 800        # Taille cible d'un chunk (mots)
    chunk_overlap: int = 100     # Mots de chevauchement entre chunks
    top_k_chunks: int = 5        # Nombre de chunks retournés par le retriever

    # ── Serveur ───────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Upload & Sécurité ─────────────────────────────────────────────────
    max_file_size_mb: int = 20
    allowed_extensions: list[str] = [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"]
    upload_dir: str = "/tmp/docsummarizer"
    # Supprimer le fichier dès que le traitement est terminé
    delete_after_processing: bool = True


# Singleton importé partout dans l'app
settings = Settings()