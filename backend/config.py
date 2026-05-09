# backend/config.py
"""
Configuration de l'application — lue depuis le fichier .env
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_groq import ChatGroq  # ← IMPORT MANQUANT


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignorer les champs supplémentaires
    )

    # ── Clés API ──────────────────────────────────────────────────────────
    groq_api_key: str = ""
    hf_token: str = "" 
    
    # ── Modèle Groq ──────────────────────────────────────────────────────────
    groq_model: str = "llama-3.3-70b-versatile"
    
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

    # ── Propriété pour obtenir le LLM (recommended) ───────────────────────────
    @property
    def llm(self):
        """Initialise le LLM Groq avec la configuration actuelle"""
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY n'est pas définie dans .env")
        return ChatGroq(
            model=self.groq_model,
            api_key=self.groq_api_key,
            temperature=0,
        )


# Créer l'instance des settings
settings = Settings()

# Optionnel : vérifier que la clé API est présente
if not settings.groq_api_key:
    print("⚠️  ATTENTION: GROQ_API_KEY non trouvée dans .env")
    print("   Le serveur pourra démarrer mais l'appel à Groq échouera.")