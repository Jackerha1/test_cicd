"""SQLAlchemy session bootstrap. All DB access goes through this `db`."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
