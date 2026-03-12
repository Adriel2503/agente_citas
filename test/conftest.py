"""Fixtures compartidos para todos los tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def id_empresa() -> int:
    """ID de empresa de prueba."""
    return 999


@pytest.fixture
def api_base_url() -> str:
    """URL base mock para la API PHP."""
    return "https://test.example.com/api"
