# backend/Dockerfile
FROM python:3.11-slim

# Installer uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dossier de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY ../pyproject.toml ../pyproject.toml
COPY . ./backend/

# Installer les dépendances
RUN uv sync --no-dev

# Copier le frontend
COPY ../frontend ./frontend/

# Port exposé
EXPOSE 8000

# Lancer le serveur
CMD ["uv", "run", "python", "backend/main.py"]