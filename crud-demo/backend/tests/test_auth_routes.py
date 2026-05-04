"""Auth route tests — register, login, password handling."""


def test_register_returns_token(client):
    r = client.post("/api/auth/register",
                    json={"username": "bob", "password": "long-enough-pw"})
    assert r.status_code == 201
    body = r.get_json()
    assert "token" in body and len(body["token"]) > 20
    assert body["username"] == "bob"


def test_register_rejects_short_password(client):
    r = client.post("/api/auth/register",
                    json={"username": "bob", "password": "short"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "validation_failed"


def test_register_rejects_invalid_username(client):
    r = client.post("/api/auth/register",
                    json={"username": "ab", "password": "long-enough-pw"})
    assert r.status_code == 400


def test_register_rejects_duplicate_username(client):
    body = {"username": "carol", "password": "long-enough-pw"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 409
    assert r.get_json()["error"] == "username_taken"


def test_login_succeeds_with_correct_password(client):
    client.post("/api/auth/register",
                json={"username": "dave", "password": "long-enough-pw"})
    r = client.post("/api/auth/login",
                    json={"username": "dave", "password": "long-enough-pw"})
    assert r.status_code == 200
    assert r.get_json()["username"] == "dave"


def test_login_rejects_wrong_password(client):
    client.post("/api/auth/register",
                json={"username": "eve", "password": "long-enough-pw"})
    r = client.post("/api/auth/login",
                    json={"username": "eve", "password": "wrong-password"})
    assert r.status_code == 401
    # Generic message — no info leak about which field failed.
    assert r.get_json()["error"] == "invalid_credentials"


def test_login_rejects_unknown_username(client):
    r = client.post("/api/auth/login",
                    json={"username": "nobody", "password": "long-enough-pw"})
    # Same generic 401 as wrong password — prevents user enumeration.
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid_credentials"


def test_password_hash_is_bcrypt_not_plaintext(app, client):
    """Ensure stored hash is a bcrypt blob, not the plaintext password."""
    from app.models import User

    client.post("/api/auth/register",
                json={"username": "frank", "password": "long-enough-pw"})

    with app.app_context():
        from app.db import db
        u = db.session.query(User).filter_by(username="frank").one()
        # bcrypt hashes start with $2a$ / $2b$ / $2y$
        assert u.password_hash.startswith("$2"), \
            "password stored as plaintext or non-bcrypt — security regression"
        assert "long-enough-pw" not in u.password_hash, \
            "plaintext leak in hash field"
