# backend/auth/google.py
"""
Authentification Google OAuth 2.0.

Flux :
  1. Frontend redirige l'utilisateur vers /auth/google/login
  2. Google redirige vers /auth/google/callback avec un code
  3. Le backend échange le code contre un access_token Google
  4. Le backend récupère le profil utilisateur via l'API Google
  5. Le backend crée/met à jour l'utilisateur en DB et retourne nos JWT

Sécurité :
  - State aléatoire (CSRF protection)
  - PKCE optionnel
  - Vérification de l'ID token Google (signature, audience, expiration)
"""

import logging
import secrets
from urllib.parse import urlencode

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token

from config import settings

logger = logging.getLogger(__name__)

#  URLs Google OAuth 
GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Scopes demandés : profil de base + email
GOOGLE_SCOPES = ["openid", "email", "profile"]


#  Génération de l'URL d'autorisation 

def build_google_auth_url(state: str) -> str:
    """
    Construit l'URL de redirection vers Google pour l'authentification.

    Args:
        state: valeur aléatoire pour la protection CSRF (stockée en session)

    Returns:
        URL complète vers Google OAuth consent screen
    """
    params = {
        "client_id":     settings.google_client_id,
        "redirect_uri":  settings.google_redirect_uri,
        "response_type": "code",
        "scope":         " ".join(GOOGLE_SCOPES),
        "state":         state,
        "access_type":   "offline",      # pour obtenir un refresh_token Google
        "prompt":        "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def generate_oauth_state() -> str:
    """Génère un state aléatoire sécurisé pour la protection CSRF."""
    return secrets.token_urlsafe(32)


#  Échange du code d'autorisation 

async def exchange_code_for_tokens(code: str) -> dict:
    """
    Échange le code d'autorisation Google contre les tokens OAuth.

    Args:
        code: code reçu dans le callback Google

    Returns:
        dict avec access_token, id_token, expires_in, etc.

    Raises:
        httpx.HTTPError: si l'échange échoue
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri":  settings.google_redirect_uri,
                "grant_type":    "authorization_code",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


# Vérification et extraction du profil 

def verify_google_id_token(id_token_str: str) -> dict:
    """
    Vérifie la signature de l'ID token Google et extrait le profil.

    La vérification inclut :
    - Signature cryptographique (clés publiques Google)
    - Audience (client_id)
    - Expiration (exp claim)
    - Émetteur (iss = accounts.google.com)

    Args:
        id_token_str: ID token JWT reçu de Google

    Returns:
        dict avec sub (google_id), email, name, picture, email_verified

    Raises:
        ValueError: si le token est invalide
    """
    try:
        idinfo = google_id_token.verify_oauth2_token(
            id_token_str,
            GoogleRequest(),
            settings.google_client_id,
            clock_skew_in_seconds=10,  # tolérance de 10s pour les décalages d'horloge
        )

        if not idinfo.get("email_verified", False):
            raise ValueError("Email Google non vérifié.")

        return {
            "google_id":     idinfo["sub"],
            "email":         idinfo["email"],
            "full_name":     idinfo.get("name", ""),
            "avatar_url":    idinfo.get("picture"),
            "email_verified": idinfo.get("email_verified", False),
        }

    except Exception as e:
        logger.error(f"Vérification ID token Google échouée : {e}")
        raise ValueError(f"Token Google invalide : {e}")


async def get_google_profile(access_token: str) -> dict:
    """
    Alternative : récupère le profil via l'API userinfo (si ID token absent).

    Args:
        access_token: Google OAuth access token

    Returns:
        dict avec le profil utilisateur
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "google_id":  data["sub"],
            "email":      data["email"],
            "full_name":  data.get("name", ""),
            "avatar_url": data.get("picture"),
        }