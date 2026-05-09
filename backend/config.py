# backend/config.py
"""
Configuration de l'application — lue depuis le fichier .env
Cherche .env dans backend/ d'abord, puis à la racine du projet.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Trouver le .env — supporte backend/.env et docsummarizer/.env
_here = Path(__file__).parent        # backend/
_root = _here.parent                 # docsummarizer/

if (_here / ".env").exists():
    _env_file = str(_here / ".env")
else:
    _env_file = str(_root / ".env")


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=_env_file,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Clé API Groq ──────────────────────────────────────────────────────────
    groq_api_key: str = ""

    # ── Modèle ChatGroq ───────────────────────────────────────────────────────
    groq_model: str = "llama-3.3-70b-versatile"

    # ── Embedding local ───────────────────────────────────────────────────────
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
print(f"[Config] .env chargé depuis : {_env_file}")
print(f"[Config] GROQ_API_KEY : {'✅ définie' if settings.groq_api_key else '❌ MANQUANTE'}")
print(f"[Config] GROQ_MODEL   : {settings.groq_model}")