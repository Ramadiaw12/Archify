# backend/auth/security.py
"""
Sécurité : hachage de mots de passe et gestion des tokens JWT.

Choix techniques :
  - bcrypt via passlib    → hachage password résistant aux attaques brute-force
  - python-jose           → génération et validation des JWT (RS256 ou HS256)
  - Deux tokens :
      access_token  (courte durée : 15 min)
      refresh_token (longue durée : 7 jours, stocké en DB pour révocation)
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

logger = logging.getLogger(__name__)

# ── Hachage mot de passe ──────────────────────────────────────────────────────

# bcrypt avec work factor 12 (bon compromis sécurité/performance en 2024)
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


def hash_password(plain_password: str) -> str:
    """
    Hache un mot de passe avec bcrypt.
    Le sel est généré automatiquement par bcrypt et inclus dans le hash.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie un mot de passe contre son hash bcrypt.
    Utilise une comparaison en temps constant pour éviter les timing attacks.
    """
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> list[str]:
    """
    Valide la robustesse d'un mot de passe.
    Retourne une liste d'erreurs (vide si valide).
    """
    errors = []
    if len(password) < 8:
        errors.append("Au moins 8 caractères requis.")
    if not any(c.isupper() for c in password):
        errors.append("Au moins une majuscule requise.")
    if not any(c.islower() for c in password):
        errors.append("Au moins une minuscule requise.")
    if not any(c.isdigit() for c in password):
        errors.append("Au moins un chiffre requis.")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        errors.append("Au moins un caractère spécial requis.")
    return errors


# ── Gestion des tokens JWT ────────────────────────────────────────────────────

def _build_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict | None = None,
) -> tuple[str, str, datetime]:
    """
    Construit un token JWT signé.

    Args:
        subject:      identifiant unique de l'utilisateur (user_id)
        token_type:   "access" ou "refresh"
        expires_delta: durée de vie du token
        extra_claims: claims supplémentaires à inclure

    Returns:
        (token_str, jti, expires_at)
    """
    now        = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    jti        = str(uuid.uuid4())   # JWT ID unique — permet la révocation individuelle

    payload = {
        "sub":  subject,          # subject (user_id)
        "type": token_type,
        "jti":  jti,
        "iat":  now,              # issued at
        "exp":  expires_at,       # expiration
        "iss":  "docsummarizer",  # issuer
    }

    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, jti, expires_at


def create_access_token(user_id: str, role: str = "user") -> tuple[str, str, datetime]:
    """
    Crée un access token JWT de courte durée (15 min par défaut).

    Returns:
        (token, jti, expires_at)
    """
    return _build_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        extra_claims={"role": role},
    )


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    """
    Crée un refresh token JWT de longue durée (7 jours par défaut).
    Stocké en DB pour permettre la révocation.

    Returns:
        (token, jti, expires_at)
    """
    return _build_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> dict:
    """
    Décode et valide un token JWT.

    Raises:
        JWTError: si le token est invalide, expiré ou malformé
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": True},
        )
        return payload
    except JWTError as e:
        logger.warning(f"Token invalide : {e}")
        raise


def extract_user_id(token: str) -> str:
    """Extrait le user_id (sub) d'un token valide."""
    payload = decode_token(token)
    return payload["sub"]