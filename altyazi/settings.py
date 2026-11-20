"""Altyazı projesi ayarları.

Ortama bağlı değerler proje kökündeki .env dosyasından okunur (bkz. .env.example).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "evet", "on"}


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "gelistirme-icin-guvensiz-anahtar-degistirin")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "glossary",
    "lectures",
    "asr",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "altyazi.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "altyazi.wsgi.application"
ASGI_APPLICATION = "altyazi.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Kanal katmanı: REDIS_URL varsa Redis, yoksa bellek içi (yalnızca tek süreçli geliştirme).
REDIS_URL = os.getenv("REDIS_URL", "").strip()
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "lectures:speaker_dashboard"
LOGOUT_REDIRECT_URL = "lectures:home"

# --- Konuşma tanıma (ASR) ayarları ---
ASR = {
    # tiny / base / small / medium / large-v3 ... (CPU için small + int8 önerilir)
    "MODEL_SIZE": os.getenv("ASR_MODEL_SIZE", "small"),
    "DEVICE": os.getenv("ASR_DEVICE", "cpu"),  # cpu / cuda / auto
    "COMPUTE_TYPE": os.getenv("ASR_COMPUTE_TYPE", "int8"),  # int8 / float16 / int8_float16 ...
    "CPU_THREADS": env_int("ASR_CPU_THREADS", 0),  # 0 = otomatik
    "MODEL_DIR": os.getenv("ASR_MODEL_DIR", "") or None,  # boşsa Hugging Face önbelleği
    "LANGUAGE": "tr",
    "BEAM_SIZE": env_int("ASR_BEAM_SIZE", 5),
    # Kısmi (gri) transkripsiyon
    "PARTIALS": env_bool("ASR_PARTIALS", True),
    "PARTIAL_INTERVAL": env_float("ASR_PARTIAL_INTERVAL", 1.2),  # saniye
    # Kısmi metin için daha hafif model (ör. base); boşsa ana model kullanılır.
    # CPU'da kesin metni (beyaz) geciktirmemek için önerilir.
    "PARTIAL_MODEL_SIZE": os.getenv("ASR_PARTIAL_MODEL_SIZE", "").strip(),
    # Bölümleme / VAD
    "MAX_SEGMENT_SECONDS": env_float("ASR_MAX_SEGMENT_SECONDS", 10.0),
    "MIN_SILENCE_MS": env_int("ASR_MIN_SILENCE_MS", 600),
    "MIN_SPEECH_MS": env_int("ASR_MIN_SPEECH_MS", 250),
    "SPEECH_PAD_MS": env_int("ASR_SPEECH_PAD_MS", 200),
    "VAD_THRESHOLD": env_float("ASR_VAD_THRESHOLD", 0.5),
    "VAD_MODEL_PATH": os.getenv("ASR_VAD_MODEL_PATH", "") or None,  # boşsa otomatik bulunur
    # initial_prompt için en fazla karakter (Whisper ~224 token sınırı)
    "PROMPT_MAX_CHARS": env_int("ASR_PROMPT_MAX_CHARS", 600),
    # Önceki cümleyi de isteme ekle. Varsayılan kapalı: Whisper, istemdeki cümleye benzeyen
    # yeni bir cümleyi "zaten yazılmış" sayıp atlayabiliyor (testlerde gözlendi).
    "PROMPT_PREVIOUS": env_bool("ASR_PROMPT_PREVIOUS", False),
}

# --- Terim eşleme ---
TERM_MATCHING = {
    "FUZZY_THRESHOLD": env_float("TERM_FUZZY_THRESHOLD", 88),
    "FUZZY_MIN_LENGTH": env_int("TERM_FUZZY_MIN_LENGTH", 5),
    "USE_ZEYREK": env_bool("TERM_USE_ZEYREK", True),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"basit": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "basit"}},
    "loggers": {
        "asr": {"handlers": ["console"], "level": os.getenv("ASR_LOG_LEVEL", "INFO")},
        "lectures": {"handlers": ["console"], "level": "INFO"},
        "glossary": {"handlers": ["console"], "level": "INFO"},
    },
}
