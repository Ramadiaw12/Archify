# backend/main.py
"""
DocSummarizer — FastAPI v2.0
Auth PostgreSQL + RAG + LangGraph + Groq
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from document_parser import DocumentParser
from agent import run_agent
from db.database import create_tables, close_db, get_session
from db.models import Summary, UserPublic
from auth.router import router as auth_router
from middleware.auth_dep import require_auth, optional_auth
from middleware.rate_limit import rate_limit_summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    try:
        await create_tables()
        logger.info("✅ PostgreSQL connecté")
    except Exception as e:
        logger.warning(f"⚠️  PostgreSQL non disponible : {e}")
    print(f"\n✅  DocSummarizer démarré → http://localhost:{settings.port}")
    print(f"🤖  Groq : {settings.groq_model}")
    print(f"🔐  Google OAuth : {'✅' if settings.google_client_id else '⚠️  non configuré'}\n")
    yield
    await close_db()
    import shutil
    shutil.rmtree(settings.upload_dir, ignore_errors=True)


app = FastAPI(
    title="DocSummarizer API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

_frontend = Path(__file__).parent.parent / "frontend"
_parser   = DocumentParser()


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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["Système"])
async def health():
    from db.database import engine
    pg_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
        pg_ok = True
    except Exception:
        pass
    return {
        "status":       "ok",
        "version":      "2.0.0",
        "groq_ready":   bool(settings.groq_api_key),
        "groq_model":   settings.groq_model,
        "postgres_ready": pg_ok,
        "google_oauth": bool(settings.google_client_id),
    }


# ── Résumé ────────────────────────────────────────────────────────────────────

@app.post("/api/summarize", tags=["Agent"])
async def summarize(
    request:            Request,
    file:               UploadFile = File(...),
    style:              str  = Form(default="concis"),
    lang:               str  = Form(default="fr"),
    detail_level:       int  = Form(default=3, ge=1, le=5),
    include_keypoints:  bool = Form(default=True),
    include_stats:      bool = Form(default=True),
    include_quotes:     bool = Form(default=False),
    include_entities:   bool = Form(default=False),
    include_conclusion: bool = Form(default=True),
    current_user:       UserPublic | None = Depends(optional_auth),
    db:                 AsyncSession = Depends(get_session),
):
    if current_user:
        rate_limit_summarize(current_user.id)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(status_code=415, detail=f"Format non supporté : {ext}")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {settings.max_file_size_mb} Mo).")

    tmp_path = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{ext}")

    try:
        with open(tmp_path, "wb") as f_out:
            f_out.write(content)

        try:
            parsed = _parser.parse(tmp_path, original_filename=file.filename or "")
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=422, detail=str(e))

        if not parsed.raw_text.strip():
            raise HTTPException(status_code=422, detail="Impossible d'extraire du texte.")

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

        summary_words = len((result["summary"] or "").split())
        compression   = round(max(0.0, (1 - summary_words / parsed.word_count) * 100), 1) if parsed.word_count > 0 else 0.0

        stats = {
            "word_count_original": parsed.word_count,
            "word_count_summary":  summary_words,
            "compression_ratio":   compression,
            "page_count":          parsed.page_count,
            "chunk_count":         len(result["chunks"]),
            "read_time_min":       max(1, round(parsed.word_count / 200)),
        }

        # Sauvegarder si connecté
        summary_id = None
        if current_user:
            try:
                summary_row = Summary(
                    user_id=current_user.id,
                    filename=file.filename or "",
                    file_type=parsed.file_type,
                    summary=result["summary"],
                    key_points=result["key_points"],
                    document_type=result["document_type"],
                    sentiment=result["sentiment"],
                    complexity=result["complexity"],
                    main_topics=result["main_topics"],
                    style=style,
                    language=lang,
                    stats=stats,
                )
                db.add(summary_row)
                await db.commit()
                await db.refresh(summary_row)
                summary_id = summary_row.id
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
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur interne : {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ── Historique ────────────────────────────────────────────────────────────────

@app.get("/api/summaries", tags=["Agent"])
async def get_summaries(
    page:         int = 1,
    per_page:     int = 10,
    current_user: UserPublic = Depends(require_auth),
    db:           AsyncSession = Depends(get_session),
):
    from sqlalchemy import desc, func
    per_page = min(per_page, 50)
    offset   = (page - 1) * per_page

    rows = await db.execute(
        select(Summary)
        .where(Summary.user_id == current_user.id)
        .order_by(desc(Summary.created_at))
        .offset(offset)
        .limit(per_page)
    )
    summaries = rows.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(Summary).where(Summary.user_id == current_user.id)
    )
    total = count_result.scalar_one()

    items = []
    for s in summaries:
        items.append({
            "id":            s.id,
            "filename":      s.filename,
            "file_type":     s.file_type,
            "summary":       s.summary[:200] + "..." if len(s.summary) > 200 else s.summary,
            "document_type": s.document_type,
            "sentiment":     s.sentiment,
            "language":      s.language,
            "created_at":    s.created_at.isoformat(),
        })

    return {
        "items":    items,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    max(1, -(-total // per_page)),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)