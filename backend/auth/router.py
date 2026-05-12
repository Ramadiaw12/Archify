# backend/auth/router.py
"""
Router FastAPI pour l'authentification.

Endpoints :
  POST /auth/register          — Inscription email/password
  POST /auth/login             — Connexion email/password
  POST /auth/logout            — Déconnexion (révocation token)
  POST /auth/refresh           — Renouvellement de tokens
  GET  /auth/me                — Profil utilisateur courant
  GET  /auth/google/login      — Redirection vers Google OAuth
  GET  /auth/google/callback   — Callback Google OAuth
"""

import secrets
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from auth import service
from auth.google import (
    build_google_auth_url,
    generate_oauth_state,
    exchange_code_for_tokens,
    verify_google_id_token,
)
from db.models import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, UserPublic,
)
from middleware.auth_dep import require_auth
from middleware.rate_limit import (
    rate_limit_login,
    rate_limit_register,
    get_client_ip,
)
from config import settings

logger   = logging.getLogger(__name__)
router   = APIRouter(prefix="/auth", tags=["Authentification"])

# Store en mémoire des states OAuth (en production : Redis)
# clé: state, valeur: timestamp de création
_oauth_states: dict[str, float] = {}


# ── Inscription email/password ────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription avec email et mot de passe",
)
async def register(
    request:      Request,
    body:         RegisterRequest,
    _rate_limit:  None = Depends(rate_limit_register),
):
    """
    Inscrit un nouvel utilisateur.

    - Email unique requis
    - Mot de passe : min 8 caractères, majuscule, chiffre, caractère spécial
    - Retourne access_token + refresh_token
    """
    ip         = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    return await service.register_email(body, user_agent=user_agent, ip_address=ip)


# ── Connexion email/password ──────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Connexion avec email et mot de passe",
)
async def login(
    request:     Request,
    body:        LoginRequest,
    _rate_limit: None = Depends(rate_limit_login),
):
    """
    Connecte un utilisateur existant.

    - Verrouillage après 5 tentatives échouées (15 min)
    - Pas de distinction email inexistant / mauvais password (anti-énumération)
    - Retourne access_token + refresh_token
    """
    ip         = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    return await service.login_email(body, user_agent=user_agent, ip_address=ip)


# ── Déconnexion ───────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Déconnexion — révocation du refresh token",
)
async def logout(body: RefreshRequest):
    """
    Révoque le refresh token en DB.
    L'access token reste valide jusqu'à son expiration naturelle (15 min).
    """
    await service.logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Rafraîchissement de tokens ────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renouvellement des tokens via refresh token",
)
async def refresh(request: Request, body: RefreshRequest):
    """
    Échange un refresh token valide contre une nouvelle paire de tokens.
    Le refresh token utilisé est immédiatement révoqué (rotation).
    """
    ip         = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    return await service.refresh_session(
        body.refresh_token,
        user_agent=user_agent,
        ip_address=ip,
    )


# ── Profil utilisateur courant ────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserPublic,
    summary="Récupérer le profil de l'utilisateur connecté",
)
async def get_me(user: UserPublic = Depends(require_auth)):
    """
    Retourne le profil de l'utilisateur authentifié.
    Nécessite : Authorization: Bearer <access_token>
    """
    return user


# ── Google OAuth — Redirection ────────────────────────────────────────────────

@router.get(
    "/google/login",
    summary="Redirection vers Google OAuth",
    response_class=RedirectResponse,
)
async def google_login():
    """
    Génère l'URL Google OAuth et redirige l'utilisateur.
    Un state aléatoire est généré pour la protection CSRF.
    """
    import time
    state = generate_oauth_state()

    # Stocker le state avec son timestamp (expiration 10 min)
    _oauth_states[state] = time.time()

    # Nettoyer les states expirés
    now     = time.time()
    expired = [s for s, t in _oauth_states.items() if now - t > 600]
    for s in expired:
        del _oauth_states[s]

    url = build_google_auth_url(state)
    return RedirectResponse(url=url, status_code=302)


# ── Google OAuth — Callback ───────────────────────────────────────────────────

@router.get(
    "/google/callback",
    response_model=TokenResponse,
    summary="Callback Google OAuth — échange du code d'autorisation",
)
async def google_callback(
    request:    Request,
    code:       str,
    state:      str,
    error:      str | None = None,
):
    """
    Reçoit le callback de Google après authentification.

    Étapes :
    1. Valider le state (CSRF)
    2. Échanger le code contre les tokens Google
    3. Vérifier l'ID token Google
    4. Créer ou connecter l'utilisateur
    5. Retourner nos JWT
    """
    import time

    # L'utilisateur a refusé la connexion Google
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connexion Google refusée : {error}",
        )

    # Vérifier le state CSRF
    if state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="State OAuth invalide ou expiré (possible attaque CSRF).",
        )

    # Vérifier que le state n'est pas expiré (10 min)
    if time.time() - _oauth_states[state] > 600:
        del _oauth_states[state]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="State OAuth expiré. Recommencez la connexion.",
        )

    del _oauth_states[state]

    # Échanger le code contre les tokens Google
    try:
        google_tokens = await exchange_code_for_tokens(code)
    except Exception as e:
        logger.error(f"Échange code Google échoué : {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible d'échanger le code Google.",
        )

    # Vérifier l'ID token et extraire le profil
    id_token_str = google_tokens.get("id_token")
    if not id_token_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID token Google manquant.",
        )

    try:
        google_profile = verify_google_id_token(id_token_str)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Créer ou connecter l'utilisateur
    ip         = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    return await service.login_or_register_google(
        google_profile,
        user_agent=user_agent,
        ip_address=ip,
    )