# backend/config.py
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cherche .env dans backend/ → racine → dossier courant
_here = Path(__file__).parent
_root = _here.parent

for _candidate in [_here / ".env", _root / ".env", Path(".env")]:
    if _candidate.exists():
        load_dotenv(_candidate, override=True)
        print(f"[Config] .env trouvé : {_candidate.resolve()}")
        break
else:
    print("[Config] ⚠️  Aucun fichier .env trouvé — variables système utilisées")


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=None,          # dotenv déjà chargé manuellement ci-dessus
        case_sensitive=False,
    )

    groq_api_key:   str  = ""
    groq_model:     str  = "llama-3.3-70b-versatile"
    embedding_model:str  = "all-MiniLM-L6-v2"
    chunk_size:     int  = 800
    chunk_overlap:  int  = 100
    top_k_chunks:   int  = 5
    host:           str  = "0.0.0.0"
    port:           int  = 8000
    debug:          bool = False
    max_file_size_mb:     int       = 20
    allowed_extensions:   list[str] = [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"]
    upload_dir:           str       = "/tmp/docsummarizer"
    delete_after_processing: bool   = True


settings = Settings()
print(f"[Config] GROQ_API_KEY : {'✅ définie' if settings.groq_api_key else '❌ MANQUANTE — ajoutez GROQ_API_KEY dans .env'}")
print(f"[Config] GROQ_MODEL   : {settings.groq_model}")