# file path: config/settings.py
from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = '&xjg@w9wz%(8sh)_fr4w(*yf8utj=3uefxtjim63#q2s#5g#r_'
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

AI_WEIGHT_PROFESSION = 35
AI_WEIGHT_SKILLS = 30
AI_WEIGHT_EXPERIENCE = 15
AI_WEIGHT_EDUCATION = 10
AI_WEIGHT_SEMANTIC = 10

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
    "site_title": "Inventory Management",
    "site_header": "Inventory Management",
    "site_brand": "Inventory Management",
    "welcome_sign": "Welcome to Inventory Management Admin",
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