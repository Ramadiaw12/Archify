# backend/auth/service.py
"""
Service d'authentification — logique métier avec PostgreSQL.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, validate_password_strength,
)
from db.models import (
    User, Session, AuthProvider, UserRole,
    UserPublic, TokenResponse, RegisterRequest, LoginRequest,
)
from config import settings

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS  = 5
LOCKOUT_DURATION_MIN = 15


# Helpers 

async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()

async def _get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def _get_user_by_google_id(db: AsyncSession, google_id: str) -> User | None:
    result = await db.execute(select(User).where(User.google_id == google_id))
    return result.scalar_one_or_none()

async def _session_exists(db: AsyncSession, jti: str) -> bool:
    result = await db.execute(select(Session).where(Session.jti == jti))
    return result.scalar_one_or_none() is not None

async def _revoke_session(db: AsyncSession, jti: str) -> None:
    result = await db.execute(select(Session).where(Session.jti == jti))
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()

async def _create_session(
    db: AsyncSession,
    user_id: str,
    jti: str,
    expires_at: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> None:
    session = Session(
        jti=jti,
        user_id=user_id,
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()

def _user_to_public(user: User) -> UserPublic:
    return UserPublic.model_validate(user)

def _make_tokens(user_id: str, role: str) -> tuple[str, str, str, datetime]:
    """Retourne (access_token, refresh_token, refresh_jti, refresh_expires_at)."""
    access_token,  _,           _           = create_access_token(user_id, role)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user_id)
    return access_token, refresh_token, refresh_jti, refresh_exp


#  Inscription email/password 

async def register_email(
    db:         AsyncSession,
    request:    RegisterRequest,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    email = request.email.lower()

    # Email déjà utilisé ?
    if await _get_user_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cet email est déjà enregistré.",
        )

    # Mot de passe assez fort ?
    errors = validate_password_strength(request.password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Mot de passe trop faible.", "errors": errors},
        )

    # Créer l'utilisateur
    user = User(
        email=email,
        full_name=request.full_name.strip(),
        hashed_password=hash_password(request.password),
        provider=AuthProvider.EMAIL,
        role=UserRole.USER,
        is_active=True,
        is_verified=False,
        last_login=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Générer tokens + session
    at, rt, rt_jti, rt_exp = _make_tokens(user.id, user.role.value)
    await _create_session(db, user.id, rt_jti, rt_exp, user_agent, ip_address)

    logger.info(f"Inscription : {email}")
    return TokenResponse(
        access_token=at,
        refresh_token=rt,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# Connexion email/password 

async def login_email(
    db:         AsyncSession,
    request:    LoginRequest,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    email = request.email.lower()
    WRONG = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email ou mot de passe incorrect.",
    )

    user = await _get_user_by_email(db, email)
    if not user:
        raise WRONG   # anti-énumération

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé.")

    # Verrouillage temporaire ?
    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        mins = int((user.locked_until - now).total_seconds() / 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Compte verrouillé. Réessayez dans {mins} min.",
        )

    if not user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="Ce compte utilise Google. Connectez-vous avec Google.",
        )

    # Mauvais mot de passe
    if not verify_password(request.password, user.hashed_password):
        failed = user.failed_attempts + 1
        locked = None
        if failed >= MAX_FAILED_ATTEMPTS:
            locked = now + timedelta(minutes=LOCKOUT_DURATION_MIN)
            logger.warning(f"Compte verrouillé : {email}")
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(failed_attempts=failed, locked_until=locked, updated_at=now)
        )
        await db.commit()
        raise WRONG

    # Connexion OK — reset compteur
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(failed_attempts=0, locked_until=None, last_login=now, updated_at=now)
    )
    await db.commit()

    at, rt, rt_jti, rt_exp = _make_tokens(user.id, user.role.value)
    await _create_session(db, user.id, rt_jti, rt_exp, user_agent, ip_address)

    logger.info(f"Connexion : {email}")
    return TokenResponse(
        access_token=at,
        refresh_token=rt,
        expires_in=settings.access_token_expire_minutes * 60,
    )


#  Connexion / Inscription Google OAuth 

async def login_or_register_google(
    db:             AsyncSession,
    google_profile: dict,
    user_agent:     str | None = None,
    ip_address:     str | None = None,
) -> TokenResponse:
    google_id = google_profile["google_id"]
    email     = google_profile["email"].lower()
    now       = datetime.now(timezone.utc)

    user = await _get_user_by_google_id(db, google_id)

    if not user:
        user = await _get_user_by_email(db, email)
        if user:
            # Lier compte Google au compte email existant
            await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(
                    google_id=google_id,
                    avatar_url=google_profile.get("avatar_url"),
                    is_verified=True,
                    last_login=now,
                    updated_at=now,
                )
            )
            await db.commit()
            await db.refresh(user)
        else:
            # Nouveau compte Google
            user = User(
                email=email,
                full_name=google_profile.get("full_name", ""),
                google_id=google_id,
                avatar_url=google_profile.get("avatar_url"),
                hashed_password=None,
                provider=AuthProvider.GOOGLE,
                role=UserRole.USER,
                is_active=True,
                is_verified=True,
                last_login=now,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
    else:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(last_login=now, updated_at=now)
        )
        await db.commit()

    at, rt, rt_jti, rt_exp = _make_tokens(user.id, user.role.value)
    await _create_session(db, user.id, rt_jti, rt_exp, user_agent, ip_address)

    logger.info(f"Connexion Google : {email}")
    return TokenResponse(
        access_token=at,
        refresh_token=rt,
        expires_in=settings.access_token_expire_minutes * 60,
    )


#  Rafraîchissement de token 

async def refresh_session(
    db:                 AsyncSession,
    refresh_token_str:  str,
    user_agent:         str | None = None,
    ip_address:         str | None = None,
) -> TokenResponse:
    try:
        payload = decode_token(refresh_token_str)
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token invalide.")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token de mauvais type.")

    jti     = payload["jti"]
    user_id = payload["sub"]

    if not await _session_exists(db, jti):
        raise HTTPException(status_code=401, detail="Session révoquée. Reconnectez-vous.")

    user = await _get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.")

    # Rotation : révoquer l'ancien + créer le nouveau
    await _revoke_session(db, jti)
    at, rt, rt_jti, rt_exp = _make_tokens(user.id, user.role.value)
    await _create_session(db, user.id, rt_jti, rt_exp, user_agent, ip_address)

    return TokenResponse(
        access_token=at,
        refresh_token=rt,
        expires_in=settings.access_token_expire_minutes * 60,
    )


#  Déconnexion 

async def logout(db: AsyncSession, refresh_token_str: str) -> None:
    try:
        payload = decode_token(refresh_token_str)
        await _revoke_session(db, payload["jti"])
    except Exception:
        pass


# Utilisateur courant 

async def get_current_user(db: AsyncSession, access_token_str: str) -> UserPublic:
    err = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(access_token_str)
    except JWTError:
        raise err

    if payload.get("type") != "access":
        raise err

    user = await _get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise err

    return _user_to_public(user)