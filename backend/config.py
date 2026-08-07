# backend/config.py
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_here = Path(__file__).parent
_root = _here.parent

for _candidate in [_here / ".env", _root / ".env", Path(".env")]:
    if _candidate.exists():
        load_dotenv(_candidate, override=True)
        print(f"[Config] .env trouvé : {_candidate.resolve()}")
        break
else:
    print("[Config] ⚠️  Aucun .env trouvé")


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    # ── Groq ──────────────────────────────────────────────────────────────────
    groq_api_key:    str = ""
    groq_model:      str = "llama-3.3-70b-versatile"
    embedding_model: str = "all-MiniLM-L6-v2"

    #  RAG 
    chunk_size:    int = 800
    chunk_overlap: int = 100
    top_k_chunks:  int = 5

    #  Serveur 
    host:  str  = "0.0.0.0"
    port:  int  = 8000
    debug: bool = False

    #  Upload 
    max_file_size_mb:        int       = 20
    allowed_extensions:      list[str] = [".pdf",".docx",".doc",".txt",".md",".rtf"]
    upload_dir:              str       = "/tmp/docsummarizer"
    delete_after_processing: bool      = True

    #  PostgreSQL 
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/docsummarizer"

    #  JWT 
    jwt_secret_key:              str = "change-me-use-openssl-rand-hex-32"
    jwt_algorithm:               str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days:   int = 7

    # Google OAuth 
    google_client_id:     str = ""
    google_client_secret: str = ""
    google_redirect_uri:  str = "http://localhost:8000/auth/google/callback"

    #  CORS 
    allowed_origins: list[str] = ["http://localhost:8000", "http://localhost:3000"]


settings = Settings()
print(f"[Config] GROQ        : {'✅' if settings.groq_api_key else '❌'}")
print(f"[Config] DATABASE    : {settings.database_url[:40]}...")
print(f"[Config] JWT         : {'✅' if 'change-me' not in settings.jwt_secret_key else '⚠️  clé par défaut'}")
print(f"[Config] GOOGLE_AUTH : {'✅' if settings.google_client_id else '⚠️  non configuré'}")