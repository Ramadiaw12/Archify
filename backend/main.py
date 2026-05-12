# backend/main.py
"""
Serveur FastAPI — DocSummarizer
Intègre : Auth (email + Google OAuth) · MongoDB · RAG + LangGraph + Groq

Endpoints publics :
  GET  /                    → Frontend HTML
  GET  /style.css           → CSS
  GET  /app.js              → JavaScript
  GET  /api/health          → Santé du serveur
  POST /auth/register       → Inscription email/password
  POST /auth/login          → Connexion email/password
  GET  /auth/google/login   → OAuth Google
  GET  /auth/google/callback→ Callback Google OAuth
  POST /auth/refresh        → Renouvellement tokens

Endpoints protégés (Bearer token) :
  GET  /auth/me             → Profil utilisateur
  POST /auth/logout         → Déconnexion
  POST /api/summarize       → Résumé de document
  GET  /api/summaries       → Historique des résumés
  GET  /api/models          → Modèles configurés
"""

import os
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config import settings
from document_parser import DocumentParser
from agent import run_agent
from db.mongo import connect_db, close_db, summaries_col
from db.models import SummaryPublic, UserPublic
from auth.router import router as auth_router
from middleware.auth_dep import require_auth, optional_auth
from middleware.rate_limit import rate_limit_summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Cycle de vie ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connexion MongoDB au démarrage, déconnexion à l'arrêt."""
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Connexion MongoDB (si configurée)
    if settings.mongo_uri:
        try:
            await connect_db()
        except Exception as e:
            logger.warning(f"⚠️  MongoDB non disponible : {e} — auth désactivée")

    print(f"\n✅  DocSummarizer démarré → http://localhost:{settings.port}")
    print(f"🤖  Modèle Groq  : {settings.groq_model}")
    print(f"🔐  Google OAuth : {'✅ configuré' if settings.google_client_id else '⚠️  non configuré'}\n")

    yield

    await close_db()
    import shutil
    shutil.rmtree(settings.upload_dir, ignore_errors=True)
    print("🔒  Serveur arrêté — fichiers temporaires supprimés.")


# ── App FastAPI ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="DocSummarizer API",
    description="Agent NLP de résumé — RAG + LangGraph + Groq + Auth MongoDB",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)

# Chemins
_frontend  = Path(__file__).parent.parent / "frontend"
_parser    = DocumentParser()


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    f = _frontend / "index.html"
    return FileResponse(str(f), media_type="text/html") if f.exists() else JSONResponse({"error": "Frontend introuvable"})

@app.get("/style.css", include_in_schema=False)
async def css():
    return FileResponse(str(_frontend / "style.css"), media_type="text/css")

@app.get("/app.js", include_in_schema=False)
async def js():
    return FileResponse(str(_frontend / "app.js"), media_type="application/javascript")


# ── Santé ─────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["Système"])
async def health():
    """Statut du serveur et des services connectés."""
    from db.mongo import _client
    mongo_ok = False
    if _client:
        try:
            await _client.admin.command("ping")
            mongo_ok = True
        except Exception:
            pass

    return {
        "status":        "ok",
        "version":       "2.0.0",
        "groq_ready":    bool(settings.groq_api_key),
        "groq_model":    settings.groq_model,
        "mongo_ready":   mongo_ok,
        "google_oauth":  bool(settings.google_client_id),
        "embedding":     settings.embedding_model,
    }


@app.get("/api/models", tags=["Système"])
async def models():
    """Modèles configurés."""
    return {
        "provider":   "Groq",
        "model":      settings.groq_model,
        "embedding":  settings.embedding_model,
        "configured": bool(settings.groq_api_key),
    }


# ── Résumé de document ────────────────────────────────────────────────────────

@app.post("/api/summarize", tags=["Agent"])
async def summarize(
    request:             Request,
    file:                UploadFile = File(...),
    style:               str  = Form(default="concis"),
    lang:                str  = Form(default="fr"),
    detail_level:        int  = Form(default=3, ge=1, le=5),
    include_keypoints:   bool = Form(default=True),
    include_stats:       bool = Form(default=True),
    include_quotes:      bool = Form(default=False),
    include_entities:    bool = Form(default=False),
    include_conclusion:  bool = Form(default=True),
    # Auth optionnelle : fonctionne sans compte, mais sauvegarde si connecté
    current_user: UserPublic | None = Depends(optional_auth),
):
    """
    Pipeline complet de résumé :
    1. Validation du fichier
    2. Extraction du texte
    3. RAG : chunking → embedding → retrieval
    4. LangGraph : classify → route → summarize (Groq)
    5. Sauvegarde en DB si l'utilisateur est connecté
    6. Suppression du fichier temporaire
    """

    # Rate limiting si utilisateur connecté
    if current_user:
        rate_limit_summarize(current_user.id)

    # Validation extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Format non supporté : {ext}. Acceptés : {', '.join(settings.allowed_extensions)}",
        )

    # Lecture + validation taille
    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop volumineux (max {settings.max_file_size_mb} Mo).",
        )

    # Sauvegarde temporaire sécurisée
    tmp_path = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{ext}")

    try:
        with open(tmp_path, "wb") as f_out:
            f_out.write(content)

        # Extraction du texte
        try:
            parsed = _parser.parse(tmp_path, original_filename=file.filename or "")
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=422, detail=str(e))

        if not parsed.raw_text.strip():
            raise HTTPException(
                status_code=422,
                detail="Impossible d'extraire du texte. Fichier protégé ou scanné sans OCR.",
            )

        # Agent LangGraph + Groq
        result = run_agent(
            raw_text=parsed.raw_text,
            filename=file.filename or "",
            style=style,
            language=lang,
            detail_level=detail_level,
            include={
                "keypoints":  include_keypoints,
                "stats":      include_stats,
                "quotes":     include_quotes,
                "entities":   include_entities,
                "conclusion": include_conclusion,
            },
        )

        if result.get("error"):
            logger.error(f"[Agent ERROR] {result['error']}")
            raise HTTPException(status_code=503, detail=result["error"])

        # Statistiques
        summary_words = len((result["summary"] or "").split())
        compression   = round(
            max(0.0, (1 - summary_words / parsed.word_count) * 100), 1
        ) if parsed.word_count > 0 else 0.0

        stats = {
            "word_count_original": parsed.word_count,
            "word_count_summary":  summary_words,
            "compression_ratio":   compression,
            "page_count":          parsed.page_count,
            "chunk_count":         len(result["chunks"]),
            "read_time_min":       max(1, round(parsed.word_count / 200)),
        }

        # Sauvegarder en DB si utilisateur connecté
        summary_id = None
        if current_user:
            try:
                doc = {
                    "user_id":       current_user.id,
                    "filename":      file.filename,
                    "file_type":     parsed.file_type,
                    "summary":       result["summary"],
                    "key_points":    result["key_points"],
                    "document_type": result["document_type"],
                    "sentiment":     result["sentiment"],
                    "complexity":    result["complexity"],
                    "main_topics":   result["main_topics"],
                    "style":         style,
                    "language":      lang,
                    "stats":         stats,
                    "created_at":    datetime.now(timezone.utc),
                }
                res = await summaries_col().insert_one(doc)
                summary_id = str(res.inserted_id)
            except Exception as e:
                logger.warning(f"Sauvegarde résumé échouée : {e}")

        return {
            "success":       True,
            "summary_id":    summary_id,
            "filename":      file.filename,
            "file_type":     parsed.file_type,
            "summary":       result["summary"],
            "key_points":    result["key_points"],
            "document_type": result["document_type"],
            "sentiment":     result["sentiment"],
            "complexity":    result["complexity"],
            "main_topics":   result["main_topics"],
            "stats":         stats,
            "pipeline": {
                "route":    result["route"],
                "language": result["language"],
                "model":    settings.groq_model,
                "provider": "Groq",
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur interne : {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ── Historique des résumés ────────────────────────────────────────────────────

@app.get("/api/summaries", tags=["Agent"])
async def get_summaries(
    page:         int = 1,
    per_page:     int = 10,
    current_user: UserPublic = Depends(require_auth),
):
    """
    Retourne l'historique des résumés de l'utilisateur connecté.
    Paginé : page=1, per_page=10 par défaut.
    """
    per_page = min(per_page, 50)   # max 50 par page
    skip     = (page - 1) * per_page

    cursor = summaries_col().find(
        {"user_id": current_user.id},
        sort=[("created_at", -1)],
        skip=skip,
        limit=per_page,
    )

    docs  = await cursor.to_list(length=per_page)
    total = await summaries_col().count_documents({"user_id": current_user.id})

    items = []
    for doc in docs:
        items.append({
            "id":            str(doc["_id"]),
            "filename":      doc["filename"],
            "file_type":     doc["file_type"],
            "summary":       doc["summary"][:200] + "..." if len(doc.get("summary","")) > 200 else doc.get("summary",""),
            "document_type": doc["document_type"],
            "sentiment":     doc["sentiment"],
            "language":      doc.get("language", "fr"),
            "created_at":    doc["created_at"].isoformat(),
        })

    return {
        "items":    items,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    max(1, -(-total // per_page)),   # ceil division
    }


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )