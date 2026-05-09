# backend/main.py
"""
Serveur FastAPI — DocSummarizer
Endpoints :
  POST /api/summarize  — Upload d'un document + résumé via agent LangGraph
  GET  /api/health     — Santé du serveur
  GET  /api/models     — Modèles configurés
  GET  /               — Sert le frontend statique (index.html)
"""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from document_parser import DocumentParser
from agent import run_agent


# ── Cycle de vie ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Création du dossier temporaire au démarrage, nettoyage à l'arrêt."""
    os.makedirs(settings.upload_dir, exist_ok=True)
    print(f"\n✅  DocSummarizer démarré → http://localhost:{settings.port}\n")
    yield
    # Nettoyage du dossier temporaire
    import shutil
    shutil.rmtree(settings.upload_dir, ignore_errors=True)
    print("🔒  Dossier temporaire nettoyé.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DocSummarizer API",
    description=(
        "Agent NLP de résumé de documents.\n"
        "Pipeline : RAG → LangGraph → Claude (Anthropic) + Groq (optionnel)"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS (à restreindre en production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chemin vers le dossier frontend (relatif à ce fichier)
_frontend_dir = Path(__file__).parent.parent / "frontend"

if not _frontend_dir.exists():
    print(f"⚠️  Dossier frontend introuvable : {_frontend_dir}")

# Singletons
_parser = DocumentParser()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    """Sert la page principale du frontend."""
    index_path = _frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return JSONResponse({"message": "DocSummarizer API — Frontend introuvable."})


@app.get("/style.css", include_in_schema=False)
async def css():
    """Sert la feuille de style."""
    return FileResponse(str(_frontend_dir / "style.css"), media_type="text/css")


@app.get("/app.js", include_in_schema=False)
async def js():
    """Sert le JavaScript principal."""
    return FileResponse(str(_frontend_dir / "app.js"), media_type="application/javascript")


@app.get("/api/health", tags=["Système"])
async def health():
    """Vérifie l'état du serveur et la disponibilité des clés API."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "groq_configured": bool(settings.groq_api_key),
        "models": {
            "llm_main":  settings.groq_model_main,
            "llm_fast":  settings.groq_model_fast,
            "embedding": settings.embedding_model,
        },
    }


@app.get("/api/models", tags=["Système"])
async def models():
    """Retourne la configuration des modèles utilisés."""
    return {
        "groq_main": {
            "provider": "Groq",
            "model":    settings.groq_model_main,
            "role":     "LLM principal — génération du résumé (llama3-70b)",
            "active":   bool(settings.groq_api_key),
        },
        "groq_fast": {
            "provider": "Groq",
            "model":    settings.groq_model_fast,
            "role":     "Pré-classification rapide du document (llama3-8b)",
            "active":   bool(settings.groq_api_key),
        },
        "embedding": {
            "provider": "SentenceTransformers (local)",
            "model":    settings.embedding_model,
            "role":     "Génération des vecteurs RAG — aucune API requise",
            "active":   True,
        },
    }


@app.post("/api/summarize", tags=["Agent"])
async def summarize(
    # Fichier
    file: UploadFile = File(..., description="Document à analyser"),
    # Options de résumé
    style: str = Form(
        default="concis",
        description="Style : concis | detaille | bullet | executif | pedagogique",
    ),
    lang: str = Form(
        default="fr",
        description="Langue du résumé : fr | en | ar | es",
    ),
    detail_level: int = Form(
        default=3, ge=1, le=5,
        description="Niveau de détail (1 = très bref, 5 = très détaillé)",
    ),
    # Éléments à inclure
    include_keypoints:  bool = Form(default=True),
    include_stats:      bool = Form(default=True),
    include_quotes:     bool = Form(default=False),
    include_entities:   bool = Form(default=False),
    include_conclusion: bool = Form(default=True),
):
    """
    Pipeline complet :
    1. Validation du fichier (extension, taille)
    2. Sauvegarde temporaire avec UUID (sécurité)
    3. Extraction du texte (DocumentParser)
    4. Agent LangGraph : chunking → embedding → retrieval → classification Groq → routage → résumé Claude
    5. Suppression du fichier temporaire
    6. Retour JSON structuré
    """

    # ── Validation ────────────────────────────────────────────────────────────
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nom de fichier manquant.",
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Extension « {ext} » non supportée. "
                f"Formats acceptés : {', '.join(settings.allowed_extensions)}"
            ),
        )

    # ── Lecture + vérification taille ─────────────────────────────────────────
    content = await file.read()
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop volumineux (max {settings.max_file_size_mb} Mo).",
        )

    # ── Sauvegarde temporaire sécurisée ───────────────────────────────────────
    # UUID pour éviter les conflits et les attaques path traversal
    tmp_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = os.path.join(settings.upload_dir, tmp_name)

    try:
        with open(tmp_path, "wb") as f_out:
            f_out.write(content)

        # ── Extraction du texte ───────────────────────────────────────────────
        try:
            parsed = _parser.parse(tmp_path, original_filename=file.filename)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

        if not parsed.raw_text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Impossible d'extraire du texte. "
                    "Le fichier est peut-être protégé ou entièrement scanné (image)."
                ),
            )

        # ── Agent LangGraph ───────────────────────────────────────────────────
        include = {
            "keypoints":  include_keypoints,
            "stats":      include_stats,
            "quotes":     include_quotes,
            "entities":   include_entities,
            "conclusion": include_conclusion,
        }

        result = run_agent(
            raw_text=parsed.raw_text,
            filename=file.filename,
            style=style,
            language=lang,
            detail_level=detail_level,
            include=include,
        )

        # ── Erreur dans le graphe ─────────────────────────────────────────────
        if result.get("error"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=result["error"],
            )

        # ── Calcul des statistiques ───────────────────────────────────────────
        summary_words = len(result["summary"].split()) if result["summary"] else 0
        compression = 0.0
        if parsed.word_count > 0:
            compression = round((1 - summary_words / parsed.word_count) * 100, 1)
            compression = max(0.0, compression)

        # ── Réponse ───────────────────────────────────────────────────────────
        return {
            "success":       True,
            "filename":      file.filename,
            "file_type":     parsed.file_type,
            # Résumé
            "summary":       result["summary"],
            "key_points":    result["key_points"],
            "document_type": result["document_type"],
            "sentiment":     result["sentiment"],
            "complexity":    result["complexity"],
            "main_topics":   result["main_topics"],
            # Statistiques
            "stats": {
                "word_count_original": parsed.word_count,
                "word_count_summary":  summary_words,
                "compression_ratio":   compression,
                "page_count":          parsed.page_count,
                "char_count":          parsed.char_count,
                "chunk_count":         len(result["chunks"]),
                "read_time_min":       max(1, round(parsed.word_count / 200)),
            },
            # Métadonnées du pipeline
            "pipeline": {
                "route":           result["route"],
                "language":        result["language"],
                "embedding_model": settings.embedding_model,
                "llm_model":       settings.groq_model_main,
                "llm_provider":    "Groq",
                "groq_meta":       result.get("groq_meta", {}),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur interne : {e}",
        )
    finally:
        # ── Suppression systématique du fichier temporaire ────────────────────
        if settings.delete_after_processing and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ── Lancement direct ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )