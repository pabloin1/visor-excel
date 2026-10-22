import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
VISOR_DATA_ROOT = Path(os.environ.get("VISOR_DATA_ROOT", BASE_DIR / "data"))
DEBUG = os.environ.get("VISOR_DEBUG", "1") == "1"
LOCAL_SECRET_KEY = "local-visor-excel-change-for-deployment"
SECRET_KEY = os.environ.get("VISOR_SECRET_KEY", LOCAL_SECRET_KEY)
if not DEBUG and SECRET_KEY == LOCAL_SECRET_KEY:
    raise ImproperlyConfigured("Configure VISOR_SECRET_KEY antes de desactivar VISOR_DEBUG.")
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get(
        "VISOR_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"
    ).split(",") if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "documents.apps.DocumentsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": VISOR_DATA_ROOT / "django.db",
        "OPTIONS": {"timeout": 20},
    },
}

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = False
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = VISOR_DATA_ROOT / "uploads"
MEDIA_URL = "/media/"
VISOR_CACHE_ROOT = VISOR_DATA_ROOT / "cache"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
