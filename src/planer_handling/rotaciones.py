"""Qué empleados trabajan cada día según su rotación (6x3, 4x4) o patrón 5x2."""
from __future__ import annotations

import re
from datetime import date

from .configuracion import Configuracion
from .modelos import Empleado


def _desfase_5x2(emp_id: str) -> int:
    digitos = re.sub(r"\D", "", emp_id) or "0"
    return int(digitos) % 7


def trabaja(empleado: Empleado, dia: date, conf: Configuracion) -> bool:
    if empleado.alta and empleado.alta > dia:
        return False
    if empleado.llamamiento and not (empleado.llamamiento[0] <= dia <= empleado.llamamiento[1]):
        return False

    if empleado.rotacion:
        patron, _, grupo = empleado.rotacion.partition("-")
        regla = conf.rotaciones[patron]
        desfase = regla["grupos"][grupo]
    else:
        regla = conf.rotaciones["5x2"]
        desfase = _desfase_5x2(empleado.id)
    ciclo = regla["trabajo"] + regla["libre"]
    return ((dia - conf.inicio_ciclos).days + desfase) % ciclo < regla["trabajo"]


def disponibles(empleados: list[Empleado], dia: date, conf: Configuracion) -> list[Empleado]:
    return [e for e in empleados if trabaja(e, dia, conf)]
