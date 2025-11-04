import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate

from extensions import db, login_manager
from user import User
from app_core import models  # noqa: F401


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

load_dotenv(os.path.join(BASE_DIR, '.env'))


def create_app():
    app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
    CORS(app)

    # Secrets & configuration
    secret = os.environ.get('SECRET_KEY', 'minha_chave_secreta')
    app.config['SECRET_KEY'] = secret
    app.secret_key = secret
    app.config['database'] = os.environ.get('APP_DATABASE', 'default')

    def _env_bool(name: str, default: bool = False) -> bool:
        return os.environ.get(name, str(default)).lower() in {'1', 'true', 'on', 'yes'}

    # Database configuration
    uri = os.getenv("DATABASE_URL", 'sqlite:///users.db')
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Feature flags & security
    app.config['ALLOW_UNCONFIRMED'] = _env_bool('ALLOW_UNCONFIRMED', False)
    app.config['FEATURE_WORKERS'] = _env_bool('FEATURE_WORKERS', False)
    app.config['FEATURE_RT3D'] = _env_bool('FEATURE_RT3D', False)
    app.config['SECURITY_EMAIL_SALT'] = os.environ.get('SECURITY_EMAIL_SALT', 'atx-email-token')
    app.config['EMAIL_CONFIRM_MAX_AGE'] = int(os.environ.get('EMAIL_CONFIRM_MAX_AGE', 60 * 60 * 24))
    app.config['PASSWORD_RESET_MAX_AGE'] = int(os.environ.get('PASSWORD_RESET_MAX_AGE', 60 * 60 * 2))

    # Mail settings
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'localhost')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 25))
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_USE_TLS'] = _env_bool('MAIL_USE_TLS', False)
    app.config['MAIL_USE_SSL'] = _env_bool('MAIL_USE_SSL', False)
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')
    app.config['MAIL_SUPPRESS_SEND'] = _env_bool('MAIL_SUPPRESS_SEND', False)

    app.config['GOOGLE_MAPS_API_KEY'] = os.environ.get('GOOGLE_MAPS_API_KEY')
    app.config.setdefault(
        'SOLID_PNG_ROOT',
        os.path.join(STATIC_DIR, 'SOLID_PRT_ASM', 'PNGS'),
    )

    storage_root = os.environ.get('STORAGE_ROOT', os.path.join(BASE_DIR, 'storage'))
    Path(storage_root).mkdir(parents=True, exist_ok=True)
    app.config['STORAGE_ROOT'] = storage_root

    db.init_app(app)
    Migrate(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'ui.login'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app_core.routes.ui import bp as ui_bp
    app.register_blueprint(ui_bp)
    from app_core.routes.projects import bp as projects_bp, api_bp as projects_api_bp
    app.register_blueprint(projects_bp)
    app.register_blueprint(projects_api_bp)

    @app.context_processor
    def inject_defaults():
        return {'current_year': datetime.utcnow().year}

    return app
