"""Configuration loaded from env. Single source of truth."""
from __future__ import annotations

import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("APP_DB_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET = os.getenv("APP_JWT_SECRET", "dev-only-change-me")
    JWT_ALGORITHM = "HS256"                      # HS256 only — see CONVENTIONS.md
    JWT_TTL_SECONDS = int(os.getenv("APP_JWT_TTL_SECONDS", "3600"))
    BCRYPT_ROUNDS = int(os.getenv("APP_BCRYPT_ROUNDS", "12"))
    CORS_ORIGIN = os.getenv("APP_CORS_ORIGIN", "http://localhost:5173")
