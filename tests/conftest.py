from pathlib import Path

import pytest

from planer_handling.configuracion import Configuracion

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def conf() -> Configuracion:
    return Configuracion.cargar(RAIZ / "config" / "base.yaml")
