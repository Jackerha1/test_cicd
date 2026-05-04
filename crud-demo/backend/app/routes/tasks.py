"""Tasks CRUD — all routes require Bearer auth."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError

from app.auth import auth_required
from app.db import db
from app.models import Task
from app.schemas import TaskCreateSchema, TaskUpdateSchema

bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")


def _own_task_or_404(task_id: int) -> Task | None:
    """Return task if it exists AND belongs to the authenticated user."""
    task = db.session.get(Task, task_id)
    if task is None or task.user_id != g.user.id:
        return None
    return task


@bp.get("")
@auth_required
def list_tasks():
    rows = (db.session.query(Task)
              .filter_by(user_id=g.user.id)
              .order_by(Task.created_at.desc())
              .all())
    return jsonify([t.to_dict() for t in rows])


@bp.post("")
@auth_required
def create_task():
    try:
        payload = TaskCreateSchema().load(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(error="validation_failed", message="invalid payload",
                       fields=exc.messages), 400

    task = Task(user_id=g.user.id, **payload)
    db.session.add(task)
    db.session.commit()
    return jsonify(task.to_dict()), 201


@bp.get("/<int:task_id>")
@auth_required
def get_task(task_id: int):
    task = _own_task_or_404(task_id)
    if task is None:
        return jsonify(error="not_found", message="task not found"), 404
    return jsonify(task.to_dict())


@bp.put("/<int:task_id>")
@auth_required
def update_task(task_id: int):
    task = _own_task_or_404(task_id)
    if task is None:
        return jsonify(error="not_found", message="task not found"), 404

    try:
        payload = TaskUpdateSchema().load(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify(error="validation_failed", message="invalid payload",
                       fields=exc.messages), 400

    for k, v in payload.items():
        setattr(task, k, v)
    db.session.commit()
    return jsonify(task.to_dict())


@bp.delete("/<int:task_id>")
@auth_required
def delete_task(task_id: int):
    task = _own_task_or_404(task_id)
    if task is None:
        return jsonify(error="not_found", message="task not found"), 404
    db.session.delete(task)
    db.session.commit()
    return "", 204
