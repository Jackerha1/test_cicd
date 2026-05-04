"""Tasks CRUD tests — auth gating, ownership isolation, validation."""


def test_list_requires_auth(client):
    r = client.get("/api/tasks")
    assert r.status_code == 401
    assert r.get_json()["error"] == "missing_token"


def test_create_and_list_task(client, auth_headers):
    create = client.post("/api/tasks",
                          json={"title": "Buy milk", "description": "2L oat"},
                          headers=auth_headers)
    assert create.status_code == 201
    body = create.get_json()
    assert body["title"] == "Buy milk"
    assert body["status"] == "todo"            # default
    assert "id" in body and "created_at" in body

    listed = client.get("/api/tasks", headers=auth_headers)
    assert listed.status_code == 200
    titles = [t["title"] for t in listed.get_json()]
    assert "Buy milk" in titles


def test_create_validates_title_required(client, auth_headers):
    r = client.post("/api/tasks", json={"description": "no title"},
                    headers=auth_headers)
    assert r.status_code == 400
    assert r.get_json()["error"] == "validation_failed"


def test_create_validates_status_enum(client, auth_headers):
    r = client.post("/api/tasks",
                    json={"title": "x", "status": "not-a-real-status"},
                    headers=auth_headers)
    assert r.status_code == 400


def test_get_returns_404_for_other_users_task(app, client, auth_headers):
    """Critical isolation test — alice must not see bob's task by ID."""
    # Create alice's task
    a = client.post("/api/tasks", json={"title": "alice task"},
                    headers=auth_headers)
    alice_task_id = a.get_json()["id"]

    # Register bob, get bob's headers
    b = client.post("/api/auth/register",
                    json={"username": "bob", "password": "long-enough-pw"})
    bob_headers = {"Authorization": f"Bearer {b.get_json()['token']}"}

    r = client.get(f"/api/tasks/{alice_task_id}", headers=bob_headers)
    # Must be 404 (not 403) — don't leak existence to the wrong user.
    assert r.status_code == 404


def test_update_changes_fields(client, auth_headers):
    created = client.post("/api/tasks", json={"title": "draft"},
                          headers=auth_headers).get_json()
    r = client.put(f"/api/tasks/{created['id']}",
                   json={"title": "final", "status": "in_progress"},
                   headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body["title"] == "final"
    assert body["status"] == "in_progress"


def test_update_returns_404_for_other_users_task(client, auth_headers):
    created = client.post("/api/tasks", json={"title": "alice task"},
                          headers=auth_headers).get_json()
    b = client.post("/api/auth/register",
                    json={"username": "mallory", "password": "long-enough-pw"})
    bad_headers = {"Authorization": f"Bearer {b.get_json()['token']}"}
    r = client.put(f"/api/tasks/{created['id']}",
                   json={"title": "hijacked"}, headers=bad_headers)
    assert r.status_code == 404


def test_delete_removes_task(client, auth_headers):
    created = client.post("/api/tasks", json={"title": "x"},
                          headers=auth_headers).get_json()
    r = client.delete(f"/api/tasks/{created['id']}", headers=auth_headers)
    assert r.status_code == 204

    follow = client.get(f"/api/tasks/{created['id']}", headers=auth_headers)
    assert follow.status_code == 404


def test_invalid_token_rejected(client):
    r = client.get("/api/tasks",
                   headers={"Authorization": "Bearer this.is.not.a.valid.jwt"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid_token"


def test_healthz_no_auth(client):
    r = client.get("/api/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "alive"
