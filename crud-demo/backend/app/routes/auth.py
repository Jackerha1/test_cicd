"""POST /api/auth/register, POST /api/auth/login."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.auth import hash_password, issue_token, verify_password
from app.db import db
from app.models import User
from app.schemas import LoginSchema, RegisterSchema

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/register")
def register():
    try:
        payload = RegisterSchema().load(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(error="validation_failed", message="invalid payload",
                       fields=exc.messages), 400

    if db.session.query(User).filter_by(username=payload["username"]).first():
        return jsonify(error="username_taken",
                       message="username already in use"), 409

    user = User(
        username=payload["username"],
        password_hash=hash_password(payload["password"]),
    )
    db.session.add(user)
    db.session.commit()

    return jsonify(token=issue_token(user), username=user.username), 201


@bp.post("/login")
def login():
    try:
        payload = LoginSchema().load(request.get_json(silent=True) or {})
    except ValidationError:
        # Don't reveal which field failed — auth endpoints stay generic.
        return jsonify(error="invalid_credentials",
                       message="invalid username or password"), 401

    user = db.session.query(User).filter_by(username=payload["username"]).first()
    if user is None or not verify_password(payload["password"], user.password_hash):
        return jsonify(error="invalid_credentials",
                       message="invalid username or password"), 401

    return jsonify(token=issue_token(user), username=user.username), 200
