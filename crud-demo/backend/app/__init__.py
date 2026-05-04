"""Flask app factory. Routes only orchestrate — see app/routes/."""
from __future__ import annotations

from flask import Flask, jsonify
from flask_cors import CORS

from app.config import Config
from app.db import db


def create_app(config: type[Config] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config or Config)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGIN"]}})

    from app.routes import auth as auth_routes
    from app.routes import tasks as tasks_routes
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(tasks_routes.bp)

    @app.get("/api/healthz")
    def healthz():
        return jsonify(status="alive")

    @app.errorhandler(404)
    def _404(_e):
        return jsonify(error="not_found", message="resource not found"), 404

    @app.errorhandler(405)
    def _405(_e):
        return jsonify(error="method_not_allowed",
                       message="method not allowed for this endpoint"), 405

    @app.errorhandler(500)
    def _500(_e):
        # Never leak stack traces to clients.
        app.logger.exception("internal_server_error")
        return jsonify(error="internal_server_error",
                       message="an unexpected error occurred"), 500

    with app.app_context():
        db.create_all()

    return app
