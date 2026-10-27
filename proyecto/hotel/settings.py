"""Configuración del proyecto de conciliación del Hotel Plaza San Francisco."""

import os
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Vercel define VERCEL en el build y en sus funciones: ahí DEBUG queda apagado salvo que se pida.
EN_VERCEL = "VERCEL" in os.environ

# Los secretos se leen del entorno. Los valores por defecto sirven solo para desarrollo local.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "solo-desarrollo-cambiar-en-produccion")
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if EN_VERCEL else "1") == "1"
# Los dominios de ngrok permiten mostrar la app desde el PC local con un túnel; .vercel.app es el hosting.
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS",
    "127.0.0.1,localhost,.vercel.app,.ngrok-free.app,.ngrok-free.dev,.ngrok.app,.ngrok.dev",
).split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "https://*.vercel.app,https://*.ngrok-free.app,https://*.ngrok-free.dev,https://*.ngrok.app,https://*.ngrok.dev",
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "conciliacion",
    # Conciliación en dólares (app "web" traída tal cual desde la rama main).
    "web",
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

ROOT_URLCONF = "hotel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "hotel.wsgi.application"

# En Vercel la base es PostgreSQL (Neon define DATABASE_URL); en local, SQLite.
if os.environ.get("DATABASE_URL"):
    _db = urllib.parse.urlparse(os.environ["DATABASE_URL"])
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _db.path.lstrip("/"),
            "USER": urllib.parse.unquote(_db.username or ""),
            "PASSWORD": urllib.parse.unquote(_db.password or ""),
            "HOST": _db.hostname,
            "PORT": _db.port or 5432,
            "OPTIONS": {"sslmode": "require"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
# Con STATIC_ROOT definido Vercel ejecuta collectstatic en el build y sirve los estáticos desde su CDN.
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# El disco de Vercel no guarda archivos entre peticiones: los archivos subidos van a Cloudflare R2 (API S3)
# cuando está configurado. Sin AWS_STORAGE_BUCKET_NAME se usa MEDIA_ROOT como en desarrollo.
if os.environ.get("AWS_STORAGE_BUCKET_NAME"):
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    # Credenciales y bucket: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME y
    # AWS_S3_ENDPOINT_URL (https://<cuenta>.r2.cloudflarestorage.com), leídos del entorno por django-storages.
    AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "auto")
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_S3_FILE_OVERWRITE = False

if not DEBUG:
    # Vercel termina HTTPS en su proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Archivos subidos grandes (el bordero mensual puede pesar varios MB).
DATA_UPLOAD_MAX_NUMBER_FILES = 60
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "conciliacion:inicio"
LOGOUT_REDIRECT_URL = "login"

# Carpeta con los datos reales de prueba (no se versionan).
CONCILIACION_DATOS_PRUEBA = os.environ.get(
    "CONCILIACION_DATOS_PRUEBA",
    str(BASE_DIR.parent.parent / "referencia" / "datos de prueba 8 sept"),
)
# Archivos de octubre: bordero .XLS de FrontOffice, cartolas BancoEstado y Transbank con todos los medios.
CONCILIACION_DATOS_OCTUBRE = os.environ.get(
    "CONCILIACION_DATOS_OCTUBRE",
    str(BASE_DIR.parent.parent / "Datos de prueba octubre"),
)
