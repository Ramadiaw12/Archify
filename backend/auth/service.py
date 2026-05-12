# backend/auth/service.py
"""
Service d'authentification — logique métier.
Orchestre la DB, le hachage de mots de passe et les JWT.

Fonctions :
  - register_email  : inscription email/password
  - login_email     : connexion email/password
  - login_google    : connexion/inscription via Google OAuth
  - refresh_session : renouvellement des tokens
  - logout          : révocation de session
  - get_current_user: récupération de l'utilisateur depuis le token
"""

import logging
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException, status
from jose import JWTError

from auth.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, validate_password_strength,
)
from db.mongo import users_col, sessions_col
from db.models import (
    UserInDB, SessionInDB, UserPublic,
    AuthProvider, UserRole,
    RegisterRequest, LoginRequest, TokenResponse,
)
from config import settings

logger = logging.getLogger(__name__)

# ── Constante : verrouillage après N tentatives échouées ─────────────────────
MAX_FAILED_ATTEMPTS   = 5
LOCKOUT_DURATION_MIN  = 15


# ── Helpers internes ──────────────────────────────────────────────────────────

async def _find_user_by_email(email: str) -> dict | None:
    return await users_col().find_one({"email": email.lower()})

async def _find_user_by_id(user_id: str) -> dict | None:
    return await users_col().find_one({"_id": ObjectId(user_id)})

async def _find_user_by_google_id(google_id: str) -> dict | None:
    return await users_col().find_one({"google_id": google_id})


def _doc_to_user_public(doc: dict) -> UserPublic:
    """Convertit un document MongoDB en UserPublic (sans données sensibles)."""
    return UserPublic(
        id=str(doc["_id"]),
        email=doc["email"],
        full_name=doc["full_name"],
        avatar_url=doc.get("avatar_url"),
        role=doc.get("role", UserRole.USER),
        provider=doc.get("provider", AuthProvider.EMAIL),
        is_verified=doc.get("is_verified", False),
        created_at=doc["created_at"],
        last_login=doc.get("last_login"),
    )


async def _create_session(
    user_id: str,
    jti: str,
    expires_at: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Enregistre une session en DB (pour la révocation de token)."""
    session = {
        "jti":        jti,
        "user_id":    user_id,
        "user_agent": user_agent,
        "ip_address": ip_address,
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    }
    await sessions_col().insert_one(session)


async def _revoke_session(jti: str) -> None:
    """Révoque une session en la supprimant de la DB."""
    await sessions_col().delete_one({"jti": jti})


async def _is_session_valid(jti: str) -> bool:
    """Vérifie qu'une session n'a pas été révoquée."""
    session = await sessions_col().find_one({"jti": jti})
    return session is not None


# ── Inscription email/password ────────────────────────────────────────────────

async def register_email(
    request: RegisterRequest,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    """
    Inscrit un nouvel utilisateur avec email/password.

    Validation :
    - Email unique
    - Robustesse du mot de passe
    - Nom complet non vide
    """
    email = request.email.lower()

    # Vérifier si l'email est déjà utilisé
    existing = await _find_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cet email est déjà enregistré.",
        )

    # Valider la robustesse du mot de passe
    errors = validate_password_strength(request.password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Mot de passe trop faible.", "errors": errors},
        )

    # Créer le document utilisateur
    now = datetime.now(timezone.utc)
    user_doc = {
        "email":           email,
        "full_name":       request.full_name.strip(),
        "hashed_password": hash_password(request.password),
        "provider":        AuthProvider.EMAIL,
        "role":            UserRole.USER,
        "is_active":       True,
        "is_verified":     False,   # nécessite confirmation email
        "failed_attempts": 0,
        "locked_until":    None,
        "avatar_url":      None,
        "google_id":       None,
        "created_at":      now,
        "updated_at":      now,
        "last_login":      now,
    }

    result = await users_col().insert_one(user_doc)
    user_id = str(result.inserted_id)

    # Générer les tokens
    access_token,  access_jti,  access_exp  = create_access_token(user_id)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user_id)

    # Enregistrer la session (refresh token)
    await _create_session(user_id, refresh_jti, refresh_exp, user_agent, ip_address)

    logger.info(f"Nouvel utilisateur inscrit : {email}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── Connexion email/password ──────────────────────────────────────────────────

async def login_email(
    request: LoginRequest,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    """
    Connecte un utilisateur via email/password.

    Sécurité :
    - Verrouillage temporaire après 5 tentatives échouées
    - Pas de distinction email inexistant / mauvais mot de passe (énumération)
    - Mise à jour du compteur de tentatives en DB
    """
    email = request.email.lower()
    GENERIC_ERROR = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email ou mot de passe incorrect.",
    )

    doc = await _find_user_by_email(email)

    # Même si l'utilisateur n'existe pas, on renvoie la même erreur (anti-énumération)
    if not doc:
        raise GENERIC_ERROR

    user_id = str(doc["_id"])

    # Vérifier si le compte est actif
    if not doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé. Contactez le support.",
        )

    # Vérifier le verrouillage temporaire
    locked_until = doc.get("locked_until")
    if locked_until and locked_until > datetime.now(timezone.utc):
        remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Compte temporairement verrouillé. Réessayez dans {remaining} minute(s).",
        )

    # Vérifier que l'utilisateur a un mot de passe (pas auth Google uniquement)
    if not doc.get("hashed_password"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce compte utilise Google. Connectez-vous avec Google.",
        )

    # Vérifier le mot de passe
    if not verify_password(request.password, doc["hashed_password"]):
        # Incrémenter le compteur de tentatives
        failed = doc.get("failed_attempts", 0) + 1
        update: dict = {"failed_attempts": failed, "updated_at": datetime.now(timezone.utc)}

        if failed >= MAX_FAILED_ATTEMPTS:
            from datetime import timedelta
            update["locked_until"] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MIN)
            logger.warning(f"Compte verrouillé après {failed} tentatives : {email}")

        await users_col().update_one({"_id": doc["_id"]}, {"$set": update})
        raise GENERIC_ERROR

    # Connexion réussie — réinitialiser le compteur
    now = datetime.now(timezone.utc)
    await users_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"failed_attempts": 0, "locked_until": None, "last_login": now, "updated_at": now}},
    )

    # Générer les tokens
    role = doc.get("role", UserRole.USER)
    access_token,  _,           access_exp  = create_access_token(user_id, role)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user_id)

    await _create_session(user_id, refresh_jti, refresh_exp, user_agent, ip_address)

    logger.info(f"Connexion réussie : {email}")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── Connexion / Inscription Google OAuth ─────────────────────────────────────

async def login_or_register_google(
    google_profile: dict,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    """
    Connecte ou inscrit un utilisateur via Google OAuth.

    Logique :
    1. Chercher par google_id → connexion directe
    2. Chercher par email → lier le compte Google existant
    3. Créer un nouveau compte Google
    """
    google_id = google_profile["google_id"]
    email     = google_profile["email"].lower()
    now       = datetime.now(timezone.utc)

    # Chercher par google_id
    doc = await _find_user_by_google_id(google_id)

    if not doc:
        # Chercher par email (compte email existant)
        doc = await _find_user_by_email(email)

        if doc:
            # Lier le compte Google au compte email existant
            await users_col().update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "google_id":  google_id,
                    "avatar_url": google_profile.get("avatar_url"),
                    "is_verified": True,   # Google garantit l'email
                    "last_login": now,
                    "updated_at": now,
                }},
            )
        else:
            # Créer un nouveau compte Google
            user_doc = {
                "email":            email,
                "full_name":        google_profile.get("full_name", ""),
                "google_id":        google_id,
                "avatar_url":       google_profile.get("avatar_url"),
                "hashed_password":  None,    # pas de password pour les comptes Google
                "provider":         AuthProvider.GOOGLE,
                "role":             UserRole.USER,
                "is_active":        True,
                "is_verified":      True,    # Google a vérifié l'email
                "failed_attempts":  0,
                "locked_until":     None,
                "created_at":       now,
                "updated_at":       now,
                "last_login":       now,
            }
            result = await users_col().insert_one(user_doc)
            doc    = await _find_user_by_id(str(result.inserted_id))
    else:
        # Compte Google existant → mettre à jour last_login
        await users_col().update_one(
            {"_id": doc["_id"]},
            {"$set": {"last_login": now, "updated_at": now}},
        )

    user_id = str(doc["_id"])
    role    = doc.get("role", UserRole.USER)

    access_token,  _,           _           = create_access_token(user_id, role)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user_id)

    await _create_session(user_id, refresh_jti, refresh_exp, user_agent, ip_address)

    logger.info(f"Connexion Google réussie : {email}")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── Rafraîchissement de token ─────────────────────────────────────────────────

async def refresh_session(
    refresh_token_str: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    """
    Renouvelle un access token via un refresh token valide.
    Rotation automatique du refresh token (old → new).
    """
    try:
        payload = decode_token(refresh_token_str)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalide ou expiré.",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de mauvais type.",
        )

    jti     = payload["jti"]
    user_id = payload["sub"]

    # Vérifier que la session n'a pas été révoquée
    if not await _is_session_valid(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session révoquée. Reconnectez-vous.",
        )

    # Récupérer l'utilisateur
    doc = await _find_user_by_id(user_id)
    if not doc or not doc.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable ou désactivé.",
        )

    # Rotation : révoquer l'ancien refresh token
    await _revoke_session(jti)

    # Créer les nouveaux tokens
    role = doc.get("role", UserRole.USER)
    access_token,  _,           _           = create_access_token(user_id, role)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user_id)

    await _create_session(user_id, refresh_jti, refresh_exp, user_agent, ip_address)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── Déconnexion ───────────────────────────────────────────────────────────────

async def logout(refresh_token_str: str) -> None:
    """Révoque le refresh token (déconnexion)."""
    try:
        payload = decode_token(refresh_token_str)
        await _revoke_session(payload["jti"])
    except Exception:
        pass   # On ne lève pas d'erreur si le token est déjà invalide


# ── Récupération de l'utilisateur courant ────────────────────────────────────

async def get_current_user(access_token_str: str) -> UserPublic:
    """
    Valide un access token et retourne l'utilisateur correspondant.
    Utilisé comme dépendance FastAPI dans les routes protégées.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(access_token_str)
    except JWTError:
        raise credentials_error

    if payload.get("type") != "access":
        raise credentials_error

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_error

    doc = await _find_user_by_id(user_id)
    if not doc or not doc.get("is_active"):
        raise credentials_error

    return _doc_to_user_public(doc)