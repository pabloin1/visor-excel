import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
VISOR_DATA_ROOT = Path(os.environ.get("VISOR_DATA_ROOT", BASE_DIR / "data"))
ON_RENDER = bool(os.environ.get("RENDER_SERVICE_ID"))
DEBUG = os.environ.get("VISOR_DEBUG", "0" if ON_RENDER else "1").lower() in {"1", "true"}
LOCAL_SECRET_KEY = "local-visor-excel-change-for-deployment"
SECRET_KEY = os.environ.get("VISOR_SECRET_KEY") or os.environ.get("SECRET_KEY", LOCAL_SECRET_KEY)
if ON_RENDER and SECRET_KEY != LOCAL_SECRET_KEY:
    # Render's generated 256-bit secret is 44 characters; Django's deploy check expects 50.
    SECRET_KEY = f"visor-excel:{SECRET_KEY}"
if not DEBUG and SECRET_KEY == LOCAL_SECRET_KEY:
    raise ImproperlyConfigured("Configure SECRET_KEY o VISOR_SECRET_KEY antes de desactivar VISOR_DEBUG.")
if ON_RENDER and DEBUG:
    raise ImproperlyConfigured("VISOR_DEBUG debe ser 0 en Render.")
render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
ALLOWED_HOSTS = [host.strip() for host in os.environ.get(
    "VISOR_ALLOWED_HOSTS", "" if ON_RENDER else "127.0.0.1,localhost,testserver"
).split(",") if host.strip()]
if render_host and render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get(
    "VISOR_CSRF_TRUSTED_ORIGINS", ""
).split(",") if origin.strip()]
if render_host:
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_host}")
VISOR_REQUIRE_LOGIN = os.environ.get("VISOR_REQUIRE_LOGIN", "1" if ON_RENDER else "0") == "1"
if ON_RENDER and not VISOR_REQUIRE_LOGIN:
    raise ImproperlyConfigured("Render necesita VISOR_REQUIRE_LOGIN=1.")
VISOR_ORIGINAL_STORAGE = os.environ.get(
    "VISOR_ORIGINAL_STORAGE", "database" if ON_RENDER else "filesystem"
)
if VISOR_ORIGINAL_STORAGE not in {"filesystem", "database"}:
    raise ImproperlyConfigured("VISOR_ORIGINAL_STORAGE debe ser filesystem o database.")
if ON_RENDER and VISOR_ORIGINAL_STORAGE != "database":
    raise ImproperlyConfigured("Render sin disco persistente necesita VISOR_ORIGINAL_STORAGE=database.")

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
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if not DEBUG else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "documents.middleware.RequireViewerLoginMiddleware",
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

if os.environ.get("DATABASE_URL"):
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=600)}
elif ON_RENDER:
    raise ImproperlyConfigured("Configure DATABASE_URL para Render.")
else:
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
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
MEDIA_ROOT = VISOR_DATA_ROOT / "uploads"
MEDIA_URL = "/media/"
VISOR_CACHE_ROOT = VISOR_DATA_ROOT / "cache"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = LOGIN_URL
if ON_RENDER and not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 3600
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
