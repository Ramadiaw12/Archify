# backend/db/database.py
"""
Connexion PostgreSQL via SQLAlchemy async + asyncpg.

Utilise :
  - SQLAlchemy 2.0 (style async)
  - asyncpg comme driver (le plus rapide pour PostgreSQL en Python)
  - Connection pool : min 5, max 20 connexions
"""

import logging
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings

logger = logging.getLogger(__name__)

# ── Engine async ──────────────────────────────────────────────────────────────
# asyncpg = driver PostgreSQL natif async, bien plus rapide que psycopg2
engine: AsyncEngine = create_async_engine(
    settings.database_url,          # postgresql+asyncpg://user:pass@host/db
    echo=settings.debug,            # log SQL si debug=True
    pool_size=5,                    # connexions permanentes
    max_overflow=15,                # connexions supplémentaires si besoin
    pool_pre_ping=True,             # vérifie que la connexion est vivante
    pool_recycle=3600,              # recycle les connexions après 1h
)

# ── Session factory ───────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,         # évite les lazy-load après commit
    autocommit=False,
    autoflush=False,
)

# ── Base des modèles ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Classe de base dont héritent tous les modèles SQLAlchemy."""
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

async def create_tables() -> None:
    """
    Crée toutes les tables définies dans les modèles.
    Appelé au démarrage de l'app (lifespan FastAPI).
    En production, utiliser Alembic pour les migrations.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Tables PostgreSQL créées / vérifiées.")


async def drop_tables() -> None:
    """Supprime toutes les tables — DANGER, uniquement pour les tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("⚠️  Toutes les tables supprimées.")


async def close_db() -> None:
    """Ferme le pool de connexions à l'arrêt de l'app."""
    await engine.dispose()
    logger.info("🔒 Pool PostgreSQL fermé.")


async def get_session() -> AsyncSession:
    """
    Dépendance FastAPI — fournit une session DB par requête.

    Usage dans un endpoint :
        async def my_route(db: AsyncSession = Depends(get_session)):
            result = await db.execute(select(User))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()