# backend/db/models.py
"""
Modèles SQLAlchemy (ORM) — tables PostgreSQL.

Tables :
  users      — utilisateurs (email/password + Google OAuth)
  sessions   — refresh tokens actifs (révocation)
  summaries  — résumés générés par utilisateur
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base


# Enums 

class AuthProvider(str, PyEnum):
    EMAIL  = "email"
    GOOGLE = "google"


class UserRole(str, PyEnum):
    USER  = "user"
    ADMIN = "admin"


# Helpers 

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _uuid() -> str:
    return str(uuid.uuid4())


#  Table : users 

class User(Base):
    """
    Utilisateur de l'application.
    Supporte deux méthodes d'auth :
      - email/password (hashed_password non null)
      - Google OAuth   (google_id non null)
    Un utilisateur peut avoir les deux (compte lié).
    """
    __tablename__ = "users"

    id              = Column(String(36),  primary_key=True,  default=_uuid)
    email           = Column(String(255), nullable=False,     unique=True,  index=True)
    full_name       = Column(String(100), nullable=False)
    avatar_url      = Column(Text,        nullable=True)
    role            = Column(Enum(UserRole), nullable=False,  default=UserRole.USER)

    # Auth email
    hashed_password = Column(String(255), nullable=True)   # None si Google only

    # Auth Google
    google_id       = Column(String(100), nullable=True,   index=True)
    provider        = Column(Enum(AuthProvider), nullable=False, default=AuthProvider.EMAIL)

    # Sécurité
    is_active       = Column(Boolean,    nullable=False,    default=True)
    is_verified     = Column(Boolean,    nullable=False,    default=False)
    failed_attempts = Column(Integer,    nullable=False,    default=0)
    locked_until    = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at      = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    last_login      = Column(DateTime(timezone=True), nullable=True)

    # Relations
    sessions        = relationship("Session",        back_populates="user", cascade="all, delete-orphan")
    summaries       = relationship("Summary",        back_populates="user", cascade="all, delete-orphan")
    documents       = relationship("Document",       back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


# Table : sessions 

class Session(Base):
    """
    Refresh token actif.
    Supprimé lors du logout ou à l'expiration.
    Permet la révocation individuelle de sessions.
    """
    __tablename__ = "sessions"

    id          = Column(String(36),  primary_key=True, default=_uuid)
    jti         = Column(String(36),  nullable=False,   unique=True,  index=True)   # JWT ID
    user_id     = Column(String(36),  ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_agent  = Column(Text,        nullable=True)
    ip_address  = Column(String(45),  nullable=True)    # IPv4 (15) ou IPv6 (45)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at  = Column(DateTime(timezone=True), nullable=False)

    # Relation
    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<Session jti={self.jti} user_id={self.user_id}>"


#  Table : summaries 

class Summary(Base):
    """
    Résumé généré par l'agent NLP, lié à un utilisateur.
    Stocke le résultat complet du pipeline RAG + Groq.
    """
    __tablename__ = "summaries"

    id            = Column(String(36),  primary_key=True, default=_uuid)
    user_id       = Column(String(36),  ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Fichier source
    filename      = Column(String(255), nullable=False)
    file_type     = Column(String(10),  nullable=False)

    # Résultat du pipeline
    summary       = Column(Text,        nullable=False)
    key_points    = Column(JSON,        nullable=False, default=list)
    document_type = Column(String(100), nullable=False, default="Document")
    sentiment     = Column(String(20),  nullable=False, default="neutre")
    complexity    = Column(String(20),  nullable=False, default="intermédiaire")
    main_topics   = Column(JSON,        nullable=False, default=list)

    # Paramètres utilisés
    style         = Column(String(20),  nullable=False, default="concis")
    language      = Column(String(5),   nullable=False, default="fr")
    stats         = Column(JSON,        nullable=False, default=dict)

    # Timestamp
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relation
    user = relationship("User", back_populates="summaries")

    __table_args__ = (
        Index("ix_summaries_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Summary id={self.id} user_id={self.user_id} file={self.filename}>"


#  Schémas Pydantic (réponses API) 
# Séparés des modèles SQLAlchemy pour découpler ORM et API

from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class UserPublic(BaseModel):
    """Données utilisateur retournées dans les réponses API."""
    id:          str
    email:       EmailStr
    full_name:   str
    avatar_url:  Optional[str]
    role:        UserRole
    provider:    AuthProvider
    is_verified: bool
    created_at:  datetime
    last_login:  Optional[datetime]

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Réponse avec les tokens JWT."""
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int   # secondes avant expiration de l'access token


class RegisterRequest(BaseModel):
    """Corps de requête pour l'inscription."""
    email:     EmailStr
    password:  str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=100)


class LoginRequest(BaseModel):
    """Corps de requête pour la connexion."""
    email:    EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Corps de requête pour le rafraîchissement de token."""
    refresh_token: str


class SummaryPublic(BaseModel):
    """Résumé retourné dans les réponses API."""
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

    model_config = {"from_attributes": True}


#  Table : documents 

class Document(Base):
    """
    Document uploadé par un utilisateur.
    Stocke le texte extrait — le fichier original est supprimé.
    Les chunks/embeddings sont stockés dans DocumentChunk.
    """
    __tablename__ = "documents"

    id          = Column(String(36),  primary_key=True, default=_uuid)
    user_id     = Column(String(36),  ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename    = Column(String(255), nullable=False)
    file_type   = Column(String(10),  nullable=False)
    raw_text    = Column(Text,        nullable=False)
    word_count  = Column(Integer,     nullable=False, default=0)
    page_count  = Column(Integer,     nullable=False, default=1)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relations
    chunks   = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    user     = relationship("User", back_populates="documents")
    chats    = relationship("Chat",          back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_documents_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<Document id={self.id} filename={self.filename}>"


#  Table : document_chunks 

class DocumentChunk(Base):
    """
    Chunks de texte avec embeddings sérialisés.
    Permet de recharger le contexte RAG depuis la DB.
    """
    __tablename__ = "document_chunks"

    id          = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer,    nullable=False)
    text        = Column(Text,       nullable=False)
    embedding   = Column(JSON,       nullable=True)   # vecteur sérialisé en liste

    # Relation
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
    )


# Table : chats 

class Chat(Base):
    """
    Session de chat sur un document.
    Un document peut avoir plusieurs sessions de chat.
    """
    __tablename__ = "chats"

    id          = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    user_id     = Column(String(36), ForeignKey("users.id",     ondelete="CASCADE"), nullable=False)
    title       = Column(String(255), nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relations
    document = relationship("Document", back_populates="chats")
    messages = relationship("ChatMessage", back_populates="chat", cascade="all, delete-orphan", order_by="ChatMessage.created_at")

    __table_args__ = (
        Index("ix_chats_document_id", "document_id"),
        Index("ix_chats_user_id",     "user_id"),
    )


#  Table : chat_messages 

class ChatMessage(Base):
    """
    Message dans une session de chat.
    role : 'user' ou 'assistant'
    """
    __tablename__ = "chat_messages"

    id         = Column(String(36), primary_key=True, default=_uuid)
    chat_id    = Column(String(36), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role       = Column(String(10), nullable=False)   # 'user' | 'assistant'
    content    = Column(Text,       nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relation
    chat = relationship("Chat", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_chat_id", "chat_id"),
    )