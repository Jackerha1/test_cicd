"""JWT issuance + Bearer-token validation decorator.

Karpathy reflex hard-coded: HS256 only. The AI-CICD policy
`jwt_none_bypass` rejects any diff that adds 'none' to algorithms — see
../../../policies/risk_rules.yaml.
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Callable

import bcrypt
import jwt
from flask import current_app, g, jsonify, request

from app.db import db
from app.models import User


def hash_password(plain: str) -> str:
    rounds = current_app.config["BCRYPT_ROUNDS"]
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def issue_token(user: User) -> str:
    cfg = current_app.config
    now = int(time.time())
    payload = {
        "sub":      str(user.id),                # RFC 7519 requires string sub
        "username": user.username,
        "iat":      now,
        "exp":      now + cfg["JWT_TTL_SECONDS"],
    }
    return jwt.encode(payload, cfg["JWT_SECRET"], algorithm=cfg["JWT_ALGORITHM"])


def _decode(token: str) -> dict:
    cfg = current_app.config
    return jwt.decode(
        token,
        cfg["JWT_SECRET"],
        algorithms=[cfg["JWT_ALGORITHM"]],   # explicit list — never accept 'none'
        options={"require": ["exp", "sub"]},
    )


def auth_required(fn: Callable) -> Callable:
    """Decorator: enforce a valid Bearer token; sets `g.user`."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            return jsonify(error="missing_token", message="Authorization header missing or malformed"), 401
        token = header.split(None, 1)[1].strip()
        try:
            payload = _decode(token)
        except jwt.ExpiredSignatureError:
            return jsonify(error="token_expired", message="Token has expired"), 401
        except jwt.InvalidTokenError as exc:
            return jsonify(error="invalid_token", message=str(exc)), 401

        try:
            user_id = int(payload["sub"])
        except (KeyError, ValueError, TypeError):
            return jsonify(error="invalid_token", message="malformed sub claim"), 401
        user = db.session.get(User, user_id)
        if user is None:
            return jsonify(error="invalid_token", message="user no longer exists"), 401
        g.user = user
        return fn(*args, **kwargs)
    return wrapper
