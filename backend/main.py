# backend/main.py
"""
Serveur FastAPI — DocSummarizer
Endpoints :
  POST /api/summarize  — Upload + résumé via agent LangGraph + Groq
  GET  /api/health     — Santé du serveur
  GET  /api/models     — Modèle configuré
  GET  /               — Frontend HTML
  GET  /style.css      — Styles
  GET  /app.js         — JavaScript
"""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config import settings
from document_parser import DocumentParser
from agent import run_agent



# ── Démarrage / arrêt ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    print(f"\n✅  DocSummarizer démarré → http://localhost:{settings.port}")
    print(f"🤖  Modèle Groq : {settings.groq_model}\n")
    yield
    import shutil
    shutil.rmtree(settings.upload_dir, ignore_errors=True)
    print("🔒  Fichiers temporaires supprimés.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DocSummarizer",
    description="Agent NLP de résumé — Pipeline : RAG + LangGraph + Groq",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chemin vers le frontend
_frontend = Path(__file__).parent.parent / "frontend"

# Singleton parseur
_parser = DocumentParser()


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


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """État du serveur."""
    return {
        "status":         "ok",
        "groq_ready":     bool(settings.groq_api_key),
        "groq_model":     settings.groq_model,
        "embedding":      settings.embedding_model,
    }


@app.get("/api/models")
async def models():
    """Modèle configuré."""
    return {
        "provider":   "Groq",
        "model":      settings.groq_model,
        "embedding":  settings.embedding_model,
        "configured": bool(settings.groq_api_key),
    }


@app.post("/api/summarize")
async def summarize(
    file:                UploadFile = File(...),
    style:               str  = Form(default="concis"),
    lang:                str  = Form(default="fr"),
    detail_level:        int  = Form(default=3, ge=1, le=5),
    include_keypoints:   bool = Form(default=True),
    include_stats:       bool = Form(default=True),
    include_quotes:      bool = Form(default=False),
    include_entities:    bool = Form(default=False),
    include_conclusion:  bool = Form(default=True),
):
    """
    Pipeline complet :
    1. Validation du fichier
    2. Extraction du texte
    3. RAG : chunking → embedding → retrieval
    4. LangGraph : classify → route → summarize (Groq)
    5. Suppression immédiate du fichier temporaire
    """

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

    # Sauvegarde temporaire avec UUID (sécurité)
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
                detail="Impossible d'extraire du texte (fichier protégé ou scanné sans OCR).",
            )

        # Agent LangGraph
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
            raise HTTPException(status_code=503, detail=result["error"])

        # Statistiques
        summary_words = len((result["summary"] or "").split())
        compression   = round(
            max(0.0, (1 - summary_words / parsed.word_count) * 100), 1
        ) if parsed.word_count > 0 else 0.0

        return {
            "success":       True,
            "filename":      file.filename,
            "file_type":     parsed.file_type,
            "summary":       result["summary"],
            "key_points":    result["key_points"],
            "document_type": result["document_type"],
            "sentiment":     result["sentiment"],
            "complexity":    result["complexity"],
            "main_topics":   result["main_topics"],
            "stats": {
                "word_count_original": parsed.word_count,
                "word_count_summary":  summary_words,
                "compression_ratio":   compression,
                "page_count":          parsed.page_count,
                "chunk_count":         len(result["chunks"]),
                "read_time_min":       max(1, round(parsed.word_count / 200)),
            },
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
        raise HTTPException(status_code=500, detail=f"Erreur interne : {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)