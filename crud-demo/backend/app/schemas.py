"""Marshmallow request validators. Routes import these — never trust raw payload."""
from __future__ import annotations

from marshmallow import Schema, fields, validate

from app.models import Task


class RegisterSchema(Schema):
    username = fields.Str(
        required=True,
        validate=[validate.Length(min=3, max=32),
                   validate.Regexp(r"^[A-Za-z0-9_-]+$")],
    )
    password = fields.Str(
        required=True,
        validate=validate.Length(min=8, max=128),
    )


class LoginSchema(Schema):
    username = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    password = fields.Str(required=True, validate=validate.Length(min=1, max=128))


class TaskCreateSchema(Schema):
    title       = fields.Str(required=True, validate=validate.Length(min=1, max=120))
    description = fields.Str(load_default=None, validate=validate.Length(max=2000))
    status      = fields.Str(load_default="todo", validate=validate.OneOf(Task.STATUS_VALUES))
    due_date    = fields.Date(load_default=None)


class TaskUpdateSchema(Schema):
    title       = fields.Str(validate=validate.Length(min=1, max=120))
    description = fields.Str(allow_none=True, validate=validate.Length(max=2000))
    status      = fields.Str(validate=validate.OneOf(Task.STATUS_VALUES))
    due_date    = fields.Date(allow_none=True)
