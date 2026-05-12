# backend/middleware/auth_dep.py
"""
Dépendances FastAPI pour l'authentification.
Utilisées avec Depends() dans les routes protégées.

Usage :
    @router.get("/me")
    async def get_me(user: UserPublic = Depends(require_auth)):
        return user

    @router.get("/admin")
    async def admin_only(user: UserPublic = Depends(require_admin)):
        return user
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.service import get_current_user
from db.models import UserPublic, UserRole

# Schéma Bearer Token — FastAPI extrait automatiquement le token du header
# Authorization: Bearer <token>
bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserPublic:
    """
    Dépendance : exige un utilisateur authentifié.
    Extrait et valide le Bearer token depuis le header Authorization.

    Raises:
        HTTP 401 si token absent ou invalide
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await get_current_user(credentials.credentials)


async def require_verified(
    user: UserPublic = Depends(require_auth),
) -> UserPublic:
    """
    Dépendance : exige un utilisateur authentifié ET avec email vérifié.

    Raises:
        HTTP 403 si email non vérifié
    """
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vérifiez votre adresse email avant de continuer.",
        )
    return user


async def require_admin(
    user: UserPublic = Depends(require_auth),
) -> UserPublic:
    """
    Dépendance : exige un utilisateur avec le rôle admin.

    Raises:
        HTTP 403 si l'utilisateur n'est pas admin
    """
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs.",
        )
    return user


async def optional_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserPublic | None:
    """
    Dépendance optionnelle : retourne l'utilisateur si authentifié, None sinon.
    Utile pour les endpoints publics qui ont un comportement enrichi si connecté.
    """
    if not credentials:
        return None
    try:
        return await get_current_user(credentials.credentials)
    except HTTPException:
        return None