# backend/db/models.py
"""
Modèles Pydantic pour la validation et la sérialisation des données MongoDB.
Chaque modèle correspond à une collection MongoDB.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId


# ── Helper ObjectId ───────────────────────────────────────────────────────────

class PyObjectId(str):
    """Conversion ObjectId MongoDB ↔ string pour Pydantic v2."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        if ObjectId.is_valid(str(v)):
            return str(v)
        raise ValueError(f"ObjectId invalide : {v}")


# ── Enums ─────────────────────────────────────────────────────────────────────

class AuthProvider(str, Enum):
    EMAIL  = "email"
    GOOGLE = "google"


class UserRole(str, Enum):
    USER  = "user"
    ADMIN = "admin"


# ── Modèle Utilisateur ────────────────────────────────────────────────────────

class UserInDB(BaseModel):
    """
    Document utilisateur stocké dans MongoDB.
    Supporte les deux méthodes d'auth : email/password et Google OAuth.
    """
    id:             Optional[str]      = Field(None, alias="_id")
    email:          EmailStr
    full_name:      str
    avatar_url:     Optional[str]      = None
    role:           UserRole           = UserRole.USER

    # Auth email/password
    hashed_password: Optional[str]    = None   # None si auth Google uniquement

    # Auth Google OAuth
    google_id:      Optional[str]      = None
    provider:       AuthProvider       = AuthProvider.EMAIL

    # Sécurité
    is_active:      bool               = True
    is_verified:    bool               = False  # email confirmé
    failed_attempts: int               = 0      # tentatives de connexion échouées
    locked_until:   Optional[datetime] = None   # verrouillage temporaire

    # Timestamps
    created_at:     datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:     datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login:     Optional[datetime] = None

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}


class UserPublic(BaseModel):
    """Données utilisateur exposées dans les réponses API (sans infos sensibles)."""
    id:         str
    email:      EmailStr
    full_name:  str
    avatar_url: Optional[str]
    role:       UserRole
    provider:   AuthProvider
    is_verified: bool
    created_at: datetime
    last_login: Optional[datetime]


# ── Modèle Session ────────────────────────────────────────────────────────────

class SessionInDB(BaseModel):
    """
    Document session stocké dans MongoDB.
    Le TTL index supprime automatiquement les sessions expirées.
    """
    id:         Optional[str]  = Field(None, alias="_id")
    jti:        str            # JWT ID unique — pour la révocation de token
    user_id:    str
    user_agent: Optional[str]  = None
    ip_address: Optional[str]  = None
    created_at: datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime       # Le TTL index MongoDB utilise ce champ

    model_config = {"populate_by_name": True}


# ── Modèle Résumé ─────────────────────────────────────────────────────────────

class SummaryInDB(BaseModel):
    """Document résumé stocké dans MongoDB, lié à un utilisateur."""
    id:            Optional[str] = Field(None, alias="_id")
    user_id:       str
    filename:      str
    file_type:     str
    summary:       str
    key_points:    list[str]    = []
    document_type: str
    sentiment:     str
    complexity:    str
    main_topics:   list[str]   = []
    style:         str
    language:      str
    stats:         dict         = {}
    created_at:    datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True}


class SummaryPublic(BaseModel):
    """Résumé exposé dans les réponses API."""
    id:            str
    filename:      str
    file_type:     str
    summary:       str
    key_points:    list[str]
    document_type: str
    sentiment:     str
    complexity:    str
    main_topics:   list[str]
    style:         str
    language:      str
    stats:         dict
    created_at:    datetime


# ── Schémas de requête ────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Corps de la requête d'inscription email/password."""
    email:     EmailStr
    password:  str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=100)


class LoginRequest(BaseModel):
    """Corps de la requête de connexion email/password."""
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    """Réponse contenant les tokens JWT."""
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int  # secondes


class RefreshRequest(BaseModel):
    """Corps de la requête de rafraîchissement de token."""
    refresh_token: str