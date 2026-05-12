# backend/middleware/auth_dep.py
"""
Dépendances FastAPI pour l'authentification — version PostgreSQL.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth.service import get_current_user
from db.database import get_session
from db.models import UserPublic, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db:          AsyncSession = Depends(get_session),
) -> UserPublic:
    """Exige un utilisateur authentifié — lève HTTP 401 sinon."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_current_user(db, credentials.credentials)


async def require_admin(
    user: UserPublic = Depends(require_auth),
) -> UserPublic:
    """Exige le rôle admin — lève HTTP 403 sinon."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs.",
        )
    return user


async def optional_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db:          AsyncSession = Depends(get_session),
) -> UserPublic | None:
    """Auth optionnelle — retourne None si non connecté."""
    if not credentials:
        return None
    try:
        return await get_current_user(db, credentials.credentials)
    except HTTPException:
        return None