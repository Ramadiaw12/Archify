# backend/auth/router.py
"""
Endpoints d'authentification — PostgreSQL version.
"""

import time
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import service
from auth.google import (
    build_google_auth_url, generate_oauth_state,
    exchange_code_for_tokens, verify_google_id_token,
)
from db.database import get_session
from db.models import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, UserPublic,
)
from middleware.auth_dep import require_auth
from middleware.rate_limit import rate_limit_login, rate_limit_register, get_client_ip
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentification"])

# Store CSRF states OAuth (en production → Redis)
_oauth_states: dict[str, float] = {}


# ── Inscription ───────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    request: Request,
    body:    RegisterRequest,
    db:      AsyncSession = Depends(get_session),
    _:       None = Depends(rate_limit_register),
):
    """Inscription avec email et mot de passe."""
    return await service.register_email(
        db, body,
        user_agent=request.headers.get("User-Agent"),
        ip_address=get_client_ip(request),
    )


# ── Connexion ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    body:    LoginRequest,
    db:      AsyncSession = Depends(get_session),
    _:       None = Depends(rate_limit_login),
):
    """Connexion avec email et mot de passe."""
    return await service.login_email(
        db, body,
        user_agent=request.headers.get("User-Agent"),
        ip_address=get_client_ip(request),
    )


# ── Déconnexion ───────────────────────────────────────────────────────────────

@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest,
    db:   AsyncSession = Depends(get_session),
):
    """Révoque le refresh token."""
    await service.logout(db, body.refresh_token)
    return Response(status_code=204)


# ── Rafraîchissement ──────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    body:    RefreshRequest,
    db:      AsyncSession = Depends(get_session),
):
    """Renouvelle les tokens via refresh token (rotation automatique)."""
    return await service.refresh_session(
        db, body.refresh_token,
        user_agent=request.headers.get("User-Agent"),
        ip_address=get_client_ip(request),
    )


# ── Profil ────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserPublic)
async def get_me(user: UserPublic = Depends(require_auth)):
    """Retourne le profil de l'utilisateur connecté."""
    return user


# ── Google OAuth — Login ──────────────────────────────────────────────────────

@router.get("/google/login", response_class=RedirectResponse)
async def google_login():
    """Redirige vers la page de connexion Google."""
    state = generate_oauth_state()
    _oauth_states[state] = time.time()

    # Nettoyer les states expirés (> 10 min)
    now     = time.time()
    expired = [s for s, t in _oauth_states.items() if now - t > 600]
    for s in expired:
        del _oauth_states[s]

    return RedirectResponse(url=build_google_auth_url(state), status_code=302)


# ── Google OAuth — Callback ───────────────────────────────────────────────────

@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(
    request: Request,
    code:    str,
    state:   str,
    error:   str | None = None,
    db:      AsyncSession = Depends(get_session),
):
    """Reçoit le callback Google, crée ou connecte l'utilisateur."""

    if error:
        raise HTTPException(status_code=400, detail=f"Connexion Google refusée : {error}")

    # Valider le state CSRF
    if state not in _oauth_states or time.time() - _oauth_states.get(state, 0) > 600:
        _oauth_states.pop(state, None)
        raise HTTPException(status_code=400, detail="State OAuth invalide ou expiré.")
    del _oauth_states[state]

    # Échanger le code
    try:
        google_tokens = await exchange_code_for_tokens(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Échange code Google échoué : {e}")

    # Vérifier l'ID token
    id_token_str = google_tokens.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=400, detail="ID token Google manquant.")

    try:
        google_profile = verify_google_id_token(id_token_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await service.login_or_register_google(
        db, google_profile,
        user_agent=request.headers.get("User-Agent"),
        ip_address=get_client_ip(request),
    )