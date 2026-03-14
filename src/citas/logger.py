"""
Sistema de logging centralizado para el agente de citas.
Configura logging consistente en toda la aplicación.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


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
        log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # File handler con rotación automática (solo si LOG_FILE está configurado).
    # Sin LOG_FILE, los logs van únicamente a stdout (ideal para Docker/Easypanel).
    # Rotación: cada archivo hasta 10 MB, se mantienen 5 backups (~60 MB máx en disco).
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            log_file,
            maxBytes=10_485_760,  # 10 MB por archivo
            backupCount=5,        # app.log, app.log.1, ..., app.log.5
            encoding='utf-8',
        ))
    
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


__all__ = ["setup_logging", "get_logger"]
