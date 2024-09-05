from pathlib import Path

import environ
from opencensus.trace import config_integration
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
HAAL_CENTRAAL_PROXY_LOG_LEVEL = env.str(
    "HAAL_CENTRAAL_PROXY_LOG_LEVEL", "DEBUG" if DEBUG else "INFO"
)
HAAL_CENTRAAL_PROXY_AUDIT_LOG_LEVEL = env.str("HAAL_CENTRAAL_PROXY_AUDIT_LOG_LEVEL", "INFO")

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
        "level": "INFO",
        "handlers": ["console"],
    },
    "loggers": {
        "opencensus": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL, "propagate": False},
        "django": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL, "propagate": False},
        "django.utils.autoreload": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "haal_centraal_proxy": {
            "handlers": ["console"],
            "level": HAAL_CENTRAAL_PROXY_LOG_LEVEL,
            "propagate": False,
        },
        "haal_centraal_proxy.audit": {
            "handlers": ["audit_console"],
            "level": HAAL_CENTRAAL_PROXY_AUDIT_LOG_LEVEL,
            "propagate": False,
        },
        "authorization_django": {
            "handlers": ["audit_console"],
            "level": HAAL_CENTRAAL_PROXY_AUDIT_LOG_LEVEL,
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

if CLOUD_ENV.lower().startswith("azure"):
    # Microsoft recommended abbreviation for Application Insights is `APPI`
    AZURE_APPI_CONNECTION_STRING: str | None = env.str("AZURE_APPI_CONNECTION_STRING")
    AZURE_APPI_AUDIT_CONNECTION_STRING: str | None = env.str("AZURE_APPI_AUDIT_CONNECTION_STRING")
    MAX_REPLICA_COUNT = env.int("MAX_REPLICA_COUNT", 5)

    MIDDLEWARE.append("opencensus.ext.django.middleware.OpencensusMiddleware")
    OPENCENSUS = {
        "TRACE": {
            "SAMPLER": "opencensus.trace.samplers.ProbabilitySampler(rate=1)",
            "EXPORTER": f"""opencensus.ext.azure.trace_exporter.AzureExporter(
                connection_string='{AZURE_APPI_CONNECTION_STRING}',
                service_name='haal-centraal-proxy'
            )""",  # noqa: E202
            "EXCLUDELIST_PATHS": [],
        }
    }
    config_integration.trace_integrations(["logging"])

    LOGGING["handlers"].update(
        {
            "azure": {
                "level": "DEBUG",
                "class": "opencensus.ext.azure.log_exporter.AzureLogHandler",
                "connection_string": AZURE_APPI_CONNECTION_STRING,
                "formatter": "json",
            },
            "audit_azure": {
                "level": "DEBUG",
                "class": "opencensus.ext.azure.log_exporter.AzureLogHandler",
                "connection_string": AZURE_APPI_AUDIT_CONNECTION_STRING,
                "formatter": "json_audit",
            },
        }
    )

    LOGGING["root"].update(
        {
            "handlers": ["azure"],
            "level": DJANGO_LOG_LEVEL,
        }
    )
    for logger_name, logger_details in LOGGING["loggers"].items():
        if "audit_console" in logger_details["handlers"]:
            LOGGING["loggers"][logger_name]["handlers"] = ["audit_azure", "console"]
        else:
            LOGGING["loggers"][logger_name]["handlers"] = ["azure", "console"]

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
HAAL_CENTRAAL_KEYFILE = env.str("HC_KEYFILE", None)
HAAL_CENTRAAL_CERTFILE = env.str("HC_CERTFILE", None)

HAAL_CENTRAAL_BRP_URL = env.str(
    "HAAL_CENTRAAL_BRP_URL",
    "https://proefomgeving.haalcentraal.nl/haalcentraal/api/brp/personen",
)
