# backend/middleware/rate_limit.py
"""
Rate limiting en mémoire (sans Redis).
Protection contre les attaques brute-force sur les endpoints d'auth.

Stratégie : sliding window par IP + par email.
En production, remplacer par slowapi + Redis pour un système distribué.
"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


#  Structure de fenêtre glissante 

@dataclass
class RateWindow:
    """Fenêtre de temps pour compter les requêtes."""
    requests:   list[float] = field(default_factory=list)  # timestamps
    _lock:      Lock        = field(default_factory=Lock, repr=False)

    def count_recent(self, window_seconds: int) -> int:
        """Retourne le nombre de requêtes dans la fenêtre de temps."""
        now    = time.time()
        cutoff = now - window_seconds
        with self._lock:
            # Nettoyer les anciennes entrées
            self.requests = [t for t in self.requests if t > cutoff]
            return len(self.requests)

    def add(self) -> None:
        """Enregistre une nouvelle requête."""
        with self._lock:
            self.requests.append(time.time())


# ── Store en mémoire ──────────────────────────────────────────────────────────

class InMemoryRateLimiter:
    """
    Rate limiter en mémoire basé sur sliding window.

    Limites configurables par endpoint :
      - /auth/login     : 10 requêtes / 15 min par IP
      - /auth/register  : 5  requêtes / 1h   par IP
      - /api/summarize  : 20 requêtes / 1h   par user
    """

    def __init__(self):
        self._windows: dict[str, RateWindow] = defaultdict(RateWindow)
        self._global_lock = Lock()

    def _get_window(self, key: str) -> RateWindow:
        with self._global_lock:
            return self._windows[key]

    def check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """
        Vérifie si la clé a dépassé la limite.

        Returns:
            True si autorisé, False si limite dépassée
        """
        window = self._get_window(key)
        count  = window.count_recent(window_seconds)

        if count >= max_requests:
            return False

        window.add()
        return True

    def cleanup(self, max_age_seconds: int = 3600) -> int:
        """
        Supprime les fenêtres inactives depuis max_age_seconds.
        À appeler périodiquement (ex: toutes les heures).
        Returns: nombre de clés supprimées
        """
        now     = time.time()
        cutoff  = now - max_age_seconds
        to_del  = []

        with self._global_lock:
            for key, window in self._windows.items():
                if not window.requests or max(window.requests) < cutoff:
                    to_del.append(key)
            for key in to_del:
                del self._windows[key]

        return len(to_del)


# ── Instance globale ──────────────────────────────────────────────────────────
limiter = InMemoryRateLimiter()


# ── Helpers FastAPI ───────────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    """
    Extrait l'IP réelle du client.
    Gère les proxies (X-Forwarded-For, X-Real-IP).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def rate_limit_login(request: Request) -> None:
    """
    Limite : 10 tentatives de connexion par IP par 15 minutes.
    Lève HTTP 429 si dépassé.
    """
    ip  = get_client_ip(request)
    key = f"login:{ip}"

    if not limiter.check(key, max_requests=10, window_seconds=900):
        logger.warning(f"Rate limit login dépassé pour IP : {ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives de connexion. Réessayez dans 15 minutes.",
            headers={"Retry-After": "900"},
        )


def rate_limit_register(request: Request) -> None:
    """
    Limite : 5 inscriptions par IP par heure.
    Lève HTTP 429 si dépassé.
    """
    ip  = get_client_ip(request)
    key = f"register:{ip}"

    if not limiter.check(key, max_requests=5, window_seconds=3600):
        logger.warning(f"Rate limit register dépassé pour IP : {ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop d'inscriptions depuis cette adresse. Réessayez dans 1 heure.",
            headers={"Retry-After": "3600"},
        )


def rate_limit_summarize(user_id: str) -> None:
    """
    Limite : 20 résumés par utilisateur par heure.
    Lève HTTP 429 si dépassé.
    """
    key = f"summarize:{user_id}"

    if not limiter.check(key, max_requests=20, window_seconds=3600):
        logger.warning(f"Rate limit summarize dépassé pour user : {user_id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Limite de 20 résumés par heure atteinte. Réessayez plus tard.",
            headers={"Retry-After": "3600"},
        )