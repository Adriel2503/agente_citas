# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Lima

WORKDIR /app

# Usuario no privilegiado (buenas prácticas)
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Instalar uv (gestor de paquetes rápido)
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# Instalar dependencias (cacheado si pyproject.toml no cambia)
COPY pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-install-project .

# Instalar paquete (solo código, sin re-descargar deps)
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps .

USER appuser

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')" || exit 1

CMD ["python", "-m", "citas.main"]
