# backend/db/mongo.py
"""
Connexion MongoDB via Motor (async).
Gère la connexion, les index et expose les collections.

Collections :
  - users       : profils utilisateurs (email/Google)
  - sessions    : tokens de session actifs
  - summaries   : résumés générés par utilisateur
"""

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure

from config import settings

logger = logging.getLogger(__name__)

# ── Client global ─────────────────────────────────────────────────────────────
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    """
    Ouvre la connexion MongoDB au démarrage de l'app.
    Appelé dans le lifespan de FastAPI.
    """
    global _client, _db
    try:
        _client = AsyncIOMotorClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=50,
            minPoolSize=5,
        )
        # Vérifier que le serveur répond
        await _client.admin.command("ping")
        _db = _client[settings.mongo_db_name]
        logger.info(f"✅ MongoDB connecté → {settings.mongo_db_name}")
        await _create_indexes()
    except ConnectionFailure as e:
        logger.error(f"❌ MongoDB connexion échouée : {e}")
        raise


async def close_db() -> None:
    """Ferme la connexion MongoDB à l'arrêt de l'app."""
    global _client
    if _client:
        _client.close()
        logger.info("🔒 MongoDB déconnecté.")


def get_db() -> AsyncIOMotorDatabase:
    """Retourne l'instance de base de données active."""
    if _db is None:
        raise RuntimeError("Base de données non initialisée. Appelez connect_db() d'abord.")
    return _db


# ── Raccourcis collections ────────────────────────────────────────────────────

def users_col():
    return get_db()["users"]

def sessions_col():
    return get_db()["sessions"]

def summaries_col():
    return get_db()["summaries"]


# ── Index ─────────────────────────────────────────────────────────────────────

async def _create_indexes() -> None:
    """
    Crée les index nécessaires pour les performances et la cohérence.
    Idempotent — peut être appelé plusieurs fois sans erreur.
    """
    db = get_db()

    # users — unicité email, recherche rapide par google_id
    await db["users"].create_index(
        [("email", ASCENDING)],
        unique=True,
        name="email_unique"
    )
    await db["users"].create_index(
        [("google_id", ASCENDING)],
        sparse=True,           # index sparse : ignore les documents sans google_id
        name="google_id_idx"
    )
    await db["users"].create_index(
        [("created_at", DESCENDING)],
        name="users_created_at"
    )

    # sessions — expiration automatique via TTL index
    await db["sessions"].create_index(
        [("expires_at", ASCENDING)],
        expireAfterSeconds=0,  # MongoDB supprime les docs quand expires_at est passé
        name="sessions_ttl"
    )
    await db["sessions"].create_index(
        [("user_id", ASCENDING)],
        name="sessions_user_id"
    )
    await db["sessions"].create_index(
        [("jti", ASCENDING)],
        unique=True,
        name="sessions_jti_unique"
    )

    # summaries — récupération par utilisateur, tri par date
    await db["summaries"].create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)],
        name="summaries_user_date"
    )

    logger.info("✅ Index MongoDB créés.")