"""Configuration classes for CPJudge."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "cpjudge-insecure-dev-secret-key-change-in-production")

    # Database configuration (SQLite default, PostgreSQL swappable via DATABASE_URL)
    raw_db_url = os.environ.get("DATABASE_URL")
    if raw_db_url:
        # SQLAlchemy 1.4+ requires 'postgresql://' instead of legacy 'postgres://'
        if raw_db_url.startswith("postgres://"):
            raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
        SQLALCHEMY_DATABASE_URI = raw_db_url
    else:
        # SQLite instance directory
        instance_dir = BASE_DIR / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{instance_dir / 'cpjudge.db'}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security limits
    # Max HTTP payload limit (16 MB for teacher ZIP test case packages and CSV rosters)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    # Max student code submission size (64 KB)
    MAX_STUDENT_CODE_BYTES = 64 * 1024

    # Rate limiting configuration (Flask-Limiter)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = "200 per day; 50 per hour"

    # CSRF protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Sandboxing settings
    USE_BWRAP = os.environ.get("USE_BWRAP", "true").lower() in ("true", "1", "yes")
    SANDBOX_USER = os.environ.get("SANDBOX_USER", "judge_sandbox")

    # Timezone settings (Pakistan Standard Time, PKT / Asia/Karachi)
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Karachi")
    TIMEZONE_LABEL = "PKT"


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False
    SECRET_KEY = os.environ.get("SECRET_KEY")


class WorkerConfig(Config):
    DEBUG = False
    SECRET_KEY = os.urandom(32)


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "worker": WorkerConfig,
    "default": DevelopmentConfig,
}
