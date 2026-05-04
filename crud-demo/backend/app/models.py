"""ORM models. Two tables: User, Task."""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Text, Date, DateTime

from app.db import db


class User(db.Model):
    __tablename__ = "users"

    id:            Mapped[int] = mapped_column(primary_key=True)
    username:      Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="owner", cascade="all, delete-orphan",
    )


class Task(db.Model):
    __tablename__ = "tasks"

    STATUS_VALUES = ("todo", "in_progress", "done")

    id:          Mapped[int] = mapped_column(primary_key=True)
    user_id:     Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                              nullable=False, index=True)
    title:       Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status:      Mapped[str] = mapped_column(String(16), default="todo", nullable=False)
    due_date:    Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                   onupdate=datetime.utcnow, nullable=False)

    owner: Mapped["User"] = relationship("User", back_populates="tasks")

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "title":       self.title,
            "description": self.description,
            "status":      self.status,
            "due_date":    self.due_date.isoformat() if self.due_date else None,
            "created_at":  self.created_at.isoformat(),
            "updated_at":  self.updated_at.isoformat(),
        }
