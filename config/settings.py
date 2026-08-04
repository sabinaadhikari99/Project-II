# file path: config/settings.py
from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv
import cloudinary
from decouple import config 
import environ

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

env = environ.Env()
# FORCE LOAD .env FILE
env.read_env(str(BASE_DIR / ".env"))

SECRET_KEY = env("SECRET_KEY")
DEBUG = os.getenv("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

INSTALLED_APPS = [
    "jazzmin",
    
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "apps.accounts",
    "apps.core.apps.CoreConfig",
    "apps.shared",
    "apps.state.apps.StateConfig",
    "apps.jobs",
    "apps.skillgap",
    "apps.recruiters",
    "apps.admin_panel",
    "apps.chatbot",
    "apps.quiz",
    "apps.external",
    "apps.notifications.apps.NotificationsConfig",
    "channels",
    "apps.cvgen",
    "drf_spectacular",
    "cloudinary",
    "cloudinary_storage",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.views.SaveDeviceInfoMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.debug",
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
            'django.template.context_processors.request',
        ]},
    }
]

WSGI_APPLICATION = "config.wsgi.application"
# ASGI_APPLICATION = "config.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        # InMemoryChannelLayer is for development only.
        # For production with multiple workers, switch to Redis:
        # "BACKEND": "channels_redis.core.RedisChannelLayer",
        # "CONFIG": {"hosts": [os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")]},
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

AI_MATCH_THRESHOLD = 70
AI_MATCH_DEBUG = False

# TEMPORARY. Logs a full per-resume, per-job pipeline trace on every AI Match
# analysis (apps.shared.match_debug). Diagnostic only - it formats values the
# analysis already produced and changes no score. Remove with match_debug.py.
AI_MATCH_TRACE = False

AI_WEIGHT_PROFESSION = 40
AI_WEIGHT_SKILLS = 30
AI_WEIGHT_EXPERIENCE = 15
AI_WEIGHT_EDUCATION = 10
AI_WEIGHT_SEMANTIC = 5

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/seeker/"
LOGOUT_REDIRECT_URL = "/login/"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8001")
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@skillsync.local")

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.getenv(
    "LINKEDIN_REDIRECT_URI",
    "http://127.0.0.1:8000/api/auth/linkedin/callback/"
)

VECTOR_STORE_DIR = BASE_DIR / "vector_store"
DATA_DIR = BASE_DIR / "data"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN") or os.getenv("APIFY_TOKEN", "")
LINKEDIN_ACTOR_ID = os.getenv("LINKEDIN_ACTOR_ID", "hKByXkMQaC5Qt9UMN")

PERFORMANCE_LOGGING_ENABLED = os.getenv("PERFORMANCE_LOGGING_ENABLED", "0") == "1"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "skillsync-cache",
    }
}

QUIZ_CACHE_TIMEOUT = 3600

SKILLGAP_CACHE_TIMEOUT = 86400
SKILLGAP_WEEKLY_HOURS = 5

# --- Persistent state layer -------------------------------------------------
# How long a user's restored state (analysis session, UI keys, quiz progress)
# may be served from cache before the DB is consulted again. Writes invalidate
# the cache explicitly, so this is only a safety net.
STATE_CACHE_TIMEOUT = 900
# The CareerContext computed for one CV is shared by the gap, courses and
# roadmap endpoints, which arrive as three separate requests. Keyed by CV
# fingerprint, so a new upload is never served a previous CV's analysis.
CAREER_CONTEXT_CACHE_TIMEOUT = 86400

SPECTACULAR_SETTINGS = {
    "TITLE": "SkillSync AI API",
    "DESCRIPTION": "API documentation",
    "VERSION": "1.0.0",

    "SECURITY": [
        {
            "BearerAuth": []
        }
    ],

    "COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
}


JAZZMIN_SETTINGS = {
    "site_title": "Skillsync AI",
    "site_header": "Skillsync AI",
    "site_brand": "Skillsync AI",
    "welcome_sign": "Welcome to Skillsync AI Admin",
    "copyright": "Sabina",
    "show_sidebar": True,
    "navigation_expanded": True,
}



LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "performance": {
            "format": "%(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
        "perf_console": {
            "class": "logging.StreamHandler",
            "formatter": "performance",
            "level": "INFO",
        },
    },
    "loggers": {
        "performance": {
            "handlers": ["perf_console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)
DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"
STATIC_URL = "/static/"
MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR/"media"

EMAIL_BACKEND ="django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT =587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
