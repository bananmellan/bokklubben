from flask import Flask

from . import db as db_module
from .auth import current_member, csrf_token, resolve_secret_key
from .config import Config
from . import services


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    data_dir = app.config["DATA_DIR"]
    data_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config["DATABASE_PATH"] = str(data_dir / "bokklubben.db")
    app.config["UPLOAD_DIR"] = upload_dir
    app.config["SECRET_KEY"] = resolve_secret_key(app)

    db_module.init_db(app)

    from . import admin, routes

    routes.register(app)
    admin.register(app)

    app.teardown_appcontext(db_module.close_db)

    @app.context_processor
    def inject_context():
        return {
            "club_name": services.get_setting("club_name", "Bokklubben"),
            "member": current_member(),
            "csrf_token": csrf_token,
            "state_labels": services.STATE_LABELS,
        }

    return app
