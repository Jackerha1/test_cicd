"""Shared pytest fixtures: in-memory DB app + authenticated client."""
from __future__ import annotations

import pytest

from app import create_app
from app.config import Config
from app.db import db


class _TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"
    BCRYPT_ROUNDS = 4                            # speed up tests; bcrypt cost is irrelevant for correctness
    TESTING = True


@pytest.fixture
def app():
    app = create_app(_TestConfig)
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered(client):
    """Register a fresh user and return (token, username)."""
    r = client.post("/api/auth/register",
                    json={"username": "alice", "password": "correct-horse-battery"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    return body["token"], body["username"]


@pytest.fixture
def auth_headers(registered):
    token, _ = registered
    return {"Authorization": f"Bearer {token}"}
