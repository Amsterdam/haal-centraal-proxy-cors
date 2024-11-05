from pathlib import Path

import environ
from pythonjsonlogger import jsonlogger

env = environ.Env()
_USE_SECRET_STORE = Path("/mnt/secrets-store").exists()

# -- Environment

SRC_DIR = Path(__file__).parents[1]

CLOUD_ENV = env.str("CLOUD_ENV", "default").lower()
DEBUG = env.bool("DJANGO_DEBUG", not bool(CLOUD_ENV))

# Whitenoise needs a place to store static files and their gzipped versions.
STATIC_ROOT = env.str("STATIC_ROOT", str(SRC_DIR.parent / "web/static"))
STATIC_URL = env.str("STATIC_URL", "/static/")

# -- Security

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env.str("SECRET_KEY", "insecure")

SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", not DEBUG)

INTERNAL_IPS = ("127.0.0.1",)

TIME_ZONE = "Europe/Amsterdam"

# -- Application definition

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "haal_centraal_proxy",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "authorization_django.authorization_middleware",
]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",  
]

if DEBUG:
    INSTALLED_APPS += [
        "debug_toolbar",
        "django_extensions",
    ]
    MIDDLEWARE.insert(1, "debug_toolbar.middleware.DebugToolbarMiddleware")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ROOT_URLCONF = "haal_centraal_proxy.urls"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(SRC_DIR / "templates")],
        "OPTIONS": {
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

if not DEBUG:
    # Keep templates in memory
    TEMPLATES[0]["OPTIONS"]["loaders"] = [
        ("django.template.loaders.cached.Loader", TEMPLATES[0]["OPTIONS"]["loaders"]),
    ]

WSGI_APPLICATION = "haal_centraal_proxy.wsgi.application"

# -- Services

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

CACHES = {"default": env.cache_url(default="locmemcache://")}

DATABASES = {}  # "default": env.db_url(default="django.db.backends.sqlite3:///tmp/db.sqlite3")}

locals().update(env.email_url(default="smtp://"))

# -- Logging


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def __init__(self, *args, **kwargs):
        # Make sure some 'extra' fields are not included:
        super().__init__(*args, **kwargs)
        self._skip_fields.update({"request": "request", "taskName": "taskName"})

    def add_fields(self, log_record: dict, record, message_dict: dict):
        # The 'rename_fields' logic fails when fields are missing, this is easier:
        super().add_fields(log_record, record, message_dict)
        # An in-place reordering, sotime/level appear first (easier for docker log scrolling)
        ordered_dict = {
            "time": log_record.pop("asctime", record.asctime),
            "level": log_record.pop("levelname", record.levelname),
            **log_record,
        }
        log_record.clear()
        log_record.update(ordered_dict)


_json_log_formatter = {
    "()": CustomJsonFormatter,
    "format": "%(asctime)s $(levelname)s %(name)s %(message)s",  # parsed as a fields list.
}

DJANGO_LOG_LEVEL = env.str("DJANGO_LOG_LEVEL", "INFO")
LOG_LEVEL = env.str("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")
AUDIT_LOG_LEVEL = env.str("AUDIT_LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "json": _json_log_formatter,
        "audit_json": {
            **_json_log_formatter,
            "static_fields": {"audit": True},
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
        "console_print": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
        },
        "audit_console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "audit_json",
        },
    },
    "root": {
        "level": DJANGO_LOG_LEVEL,
        "handlers": ["console"],
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL, "propagate": False},
        "django.utils.autoreload": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "haal_centraal_proxy": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "haal_centraal_proxy.audit": {
            "handlers": ["audit_console"],
            "level": AUDIT_LOG_LEVEL,
            "propagate": False,
        },
        "authorization_django": {
            "handlers": ["audit_console"],
            "level": AUDIT_LOG_LEVEL,
            "propagate": False,
        },
        "apikeyclient": {"handlers": ["console"], "propagate": False},
    },
}

if DEBUG:
    # Print tracebacks without JSON formatting.
    LOGGING["loggers"]["django.request"] = {
        "handlers": ["console_print"],
        "level": "ERROR",
        "propagate": False,
    }

# -- Azure specific settings
if CLOUD_ENV.startswith("azure"):
    APPLICATIONINSIGHTS_CONNECTION_STRING = env.str("APPLICATIONINSIGHTS_CONNECTION_STRING")
    APPLICATIONINSIGHTS_AUDIT_CONNECTION_STRING: str | None = env.str(
        "APPLICATIONINSIGHTS_AUDIT_CONNECTION_STRING", None
    )
    MAX_REPLICA_COUNT = env.int("MAX_REPLICA_COUNT", 5)

    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes

    # Configure OpenTelemetry to use Azure Monitor with the specified connection string
    if APPLICATIONINSIGHTS_CONNECTION_STRING is not None:
        configure_azure_monitor(
            connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING,
            logger_name="root",
            instrumentation_options={
                "azure_sdk": {"enabled": False},
                "django": {"enabled": False},  # Manually done
                "fastapi": {"enabled": False},
                "flask": {"enabled": False},
                "psycopg2": {"enabled": False},  # Manually done
                "requests": {"enabled": True},
                "urllib": {"enabled": True},
                "urllib3": {"enabled": True},
            },
            resource=Resource.create({ResourceAttributes.SERVICE_NAME: "haal-centraal-proxy"}),
        )
        print("OpenTelemetry has been enabled")

        def response_hook(span, request, response):
            if (
                span.is_recording()
                and hasattr(request, "get_token_claims")
                and (email := request.get_token_claims.get("email", request.get_token_subject))
            ):
                span.set_attribute("user.AuthenticatedId", email)

        DjangoInstrumentor().instrument(response_hook=response_hook)
        print("Django instrumentor enabled")

        # Psycopg2Instrumentor().instrument(enable_commenter=True, commenter_options={})
        # print("Psycopg instrumentor enabled")


# -- Third party app settings

HEALTH_CHECKS = {
    "app": lambda request: True,
    # "database": "django_healthchecks.contrib.check_database",
    # 'cache': 'django_healthchecks.contrib.check_cache_default',
    # 'ip': 'django_healthchecks.contrib.check_remote_addr',
}
HEALTH_CHECKS_ERROR_CODE = 503

REST_FRAMEWORK = dict(
    EXCEPTION_HANDLER="haal_centraal_proxy.views.exception_handler",
    UNAUTHENTICATED_USER=None,  # Avoid importing django.contrib.auth.models
    UNAUTHENTICATED_TOKEN=None,
    URL_FORMAT_OVERRIDE="_format",  # use ?_format=.. instead of ?format=..
)

# -- Amsterdam oauth settings

DATAPUNT_AUTHZ = {
    # To verify JWT tokens, either the PUB_JWKS or a OAUTH_JWKS_URL needs to be set.
    "JWKS": env.str("PUB_JWKS", None),
    "JWKS_URL": env.str("OAUTH_JWKS_URL", None),
    # "ALWAYS_OK": True if DEBUG else False,
    "ALWAYS_OK": False,
    "MIN_INTERVAL_KEYSET_UPDATE": 30 * 60,  # 30 minutes
}

# -- Local app settings

if _USE_SECRET_STORE or CLOUD_ENV.startswith("azure"):
    HAAL_CENTRAAL_API_KEY = Path("/mnt/secrets-store/haal-centraal-proxy-key").read_text()
else:
    HAAL_CENTRAAL_API_KEY = env.str("HAAL_CENTRAAL_API_KEY", "")

# mTLS client certificate for Haal Centraal BRK.
HAAL_CENTRAAL_KEY_FILE = env.str("HAAL_CENTRAAL_KEY_FILE", None)
HAAL_CENTRAAL_CERT_FILE = env.str("HAAL_CENTRAAL_CERT_FILE", None)

HAAL_CENTRAAL_BRP_URL = env.str(
    "HAAL_CENTRAAL_BRP_URL",
    "https://proefomgeving.haalcentraal.nl/haalcentraal/api/brp/personen",
)
