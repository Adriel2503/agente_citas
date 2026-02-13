"""
Configuración del agente de citas (env, credenciales).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env en la raíz del proyecto agent_citas (src/citas/config/config.py -> agent_citas)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_BASE_DIR / ".env")

# OpenAI (agente especializado en citas)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.5"))

# Configuración del servidor
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8003"))

# Base de datos (futuro)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Redis (futuro)
REDIS_URL = os.getenv("REDIS_URL", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "")  # Si está vacío, no guarda en archivo

# Timeouts (configurables)
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "90"))
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))

# Cache
SCHEDULE_CACHE_TTL_MINUTES = int(os.getenv("SCHEDULE_CACHE_TTL_MINUTES", "5"))

# APIs MaravIA (calendario, agendar reunión, información/horarios)
API_CALENDAR_URL = os.getenv(
    "API_CALENDAR_URL",
    "https://api.maravia.pe/servicio/ws_calendario.php",
)
API_AGENDAR_REUNION_URL = os.getenv(
    "API_AGENDAR_REUNION_URL",
    "https://api.maravia.pe/servicio/ws_agendar_reunion.php",
)
API_INFORMACION_URL = os.getenv(
    "API_INFORMACION_URL",
    "https://api.maravia.pe/servicio/ws_informacion_ia.php",
)

# Zona horaria (fecha/hora en prompts y validación)
TIMEZONE = os.getenv("TIMEZONE", "America/Lima")
