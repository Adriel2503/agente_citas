"""
Sistema de logging centralizado para el agente de citas.
Configura logging consistente en toda la aplicación.
"""

import logging
import sys
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Trace ID por request — se setea en main.py al recibir cada request.
# ContextVar propaga automáticamente a todas las coroutines hijas.
trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


class _TraceFilter(logging.Filter):
    """Inyecta trace_id en cada log record para correlacionar logs por request."""

    def filter(self, record):
        record.trace_id = trace_id.get()
        return True


def setup_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
    log_format: str | None = None
) -> None:
    """
    Configura el sistema de logging para toda la aplicación.
    
    Args:
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Ruta al archivo de log (opcional)
        log_format: Formato personalizado de log (opcional)
    """
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - [trace=%(trace_id)s] - %(message)s'

    _trace_filter = _TraceFilter()

    handlers = [logging.StreamHandler(sys.stdout)]
    
    # File handler con rotación diaria (solo si LOG_FILE está configurado).
    # Sin LOG_FILE, los logs van únicamente a stdout (ideal para Docker/Easypanel).
    # Rotación: cada medianoche genera un archivo con la fecha embebida en el nombre.
    # Se conservan 30 días → ~31 archivos en disco (actual + 30 rotados).
    # Formato resultante: agent_citas_2026-05-11.log (fecha antes de la extensión).
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8',
            utc=False,
        )
        file_handler.suffix = "%Y-%m-%d"

        # Renombrar al rotar: "agent_citas.log.2026-05-11" → "agent_citas_2026-05-11.log"
        _stem = log_path.stem        # "agent_citas"
        _ext = log_path.suffix       # ".log"
        _dir = str(log_path.parent)

        def _namer(default_name: str, stem=_stem, ext=_ext, dir_=_dir) -> str:
            # default_name viene como ".../agent_citas.log.2026-05-11"
            date_part = default_name.rsplit(".", 1)[-1]
            return f"{dir_}/{stem}_{date_part}{ext}"

        file_handler.namer = _namer
        handlers.append(file_handler)
    
    # Agregar trace filter a todos los handlers
    for handler in handlers:
        handler.addFilter(_trace_filter)

    # Configurar logging root
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=handlers,
        force=True  # Sobreescribir configuración existente
    )
    
    # Silenciar loggers ruidosos de terceros
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Obtiene un logger con el nombre especificado.
    
    Args:
        name: Nombre del logger (usualmente __name__ del módulo)
    
    Returns:
        Logger configurado
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Mensaje de log")
    """
    return logging.getLogger(name)


__all__ = ["setup_logging", "get_logger", "trace_id"]
