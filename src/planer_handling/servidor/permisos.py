"""Quién puede ver y cambiar qué.

Dos niveles:
  1. Administrador de AEROS (nosotros): da de alta empresas y bases y activa las herramientas que
     cada base tiene contratadas. No entra en los datos de las bases.
  2. La central de cada empresa: ve y cambia todo en todas sus bases, crea usuarios y les da bases.
Dentro de una base, cada usuario tiene un rol (jefe de base, planificador o consulta) y, si la
central quiere, solo algunas de las herramientas de la base.
"""
from __future__ import annotations

from .modelo import Acceso, Base, Usuario

# Herramienta -> pestañas de la web que abre. "reglas" es de la empresa entera, no de una base.
HERRAMIENTAS = {
    "datos": "Datos (cuadrante real, vuelos, contratos, formación)",
    "cuadrante": "Cuadrante del mes y resumen de cobertura",
    "parrilla": "Parrilla del día",
    "pasaje": "Pasaje (facturación, embarque, oficina…)",
    "ausencias": "Plantilla y ausencias, reorganizar",
    "rotaciones": "Rotaciones del año",
    "vacaciones": "Vacaciones por puntos",
    "personal": "Buscar y filtrar personal",
}
TODAS = list(HERRAMIENTAS)

ROLES = {
    "jefe_base": "Jefe de base",
    "planificador": "Planificador / RAMPCO",
    "consulta": "Consulta (solo ver)",
}
# Qué puede hacer cada rol con las herramientas que tiene.
EDITA = {"jefe_base": True, "planificador": True, "consulta": False}


class SinPermiso(PermissionError):
    pass


def _acceso(usuario: Usuario, base: Base) -> Acceso | None:
    return next((a for a in usuario.accesos if a.base_id == base.id), None)


def ve_base(usuario: Usuario, base: Base) -> bool:
    if not (usuario.activo and base.activa and base.empresa.activa) or usuario.admin_aeros:
        return False
    if usuario.empresa_id != base.empresa_id:
        return False                     # nunca otra empresa, aunque haya un acceso mal puesto
    return usuario.central or _acceso(usuario, base) is not None


def herramientas(usuario: Usuario, base: Base) -> dict[str, bool]:
    """Herramienta -> si puede cambiar (True) o solo ver (False). Solo las contratadas por la base."""
    if not ve_base(usuario, base):
        return {}
    contratadas = [h for h in TODAS if h in (base.herramientas or [])]
    if usuario.central:
        return {h: True for h in contratadas}
    acceso = _acceso(usuario, base)
    permitidas = contratadas if acceso.herramientas is None else [h for h in contratadas if h in acceso.herramientas]
    return {h: EDITA.get(acceso.rol, False) for h in permitidas}


def puede(usuario: Usuario, base: Base, herramienta: str, cambiar: bool = False) -> bool:
    h = herramientas(usuario, base)
    return herramienta in h and (h[herramienta] or not cambiar)


def exigir(usuario: Usuario, base: Base, herramienta: str, cambiar: bool = False) -> None:
    if not puede(usuario, base, herramienta, cambiar):
        raise SinPermiso(f"{usuario.usuario} no puede {'cambiar' if cambiar else 'ver'} «{herramienta}» en "
                         f"{base.codigo}.")


def cambia_reglas(usuario: Usuario) -> bool:
    """Las reglas de la empresa (turnos, contratos, convenio…) solo las cambia la central."""
    return usuario.activo and usuario.central and not usuario.admin_aeros


def gestiona_usuarios(usuario: Usuario) -> bool:
    return usuario.activo and usuario.central and not usuario.admin_aeros
