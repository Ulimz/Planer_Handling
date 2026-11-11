"""Empresa y base piloto con datos ficticios (ver scripts/plantilla_ficticia.py), para probar el
servidor de punta a punta: cuentas de cada rol, datos subidos y fichas de personal."""
from __future__ import annotations

import secrets
from pathlib import Path

from ..archivo import Archivo
from ..configuracion import Configuracion
from ..importar.contratos import leer_contratos
from ..importar.cuadrante import leer_cuadrante
from ..importar.habilitaciones import leer_habilitaciones
from ..importar.vuelos import leer_vuelos
from ..mensual import dias_del_mes
from ..registro import Almacen
from .personal import fichas_de_la_base
from .servicio import ErrorDatos, Servidor

RAIZ = Path(__file__).resolve().parents[3]
CUENTAS = [("central.piloto", None), ("jefe.pil", "jefe_base"), ("planif.pil", "planificador"),
           ("consulta.pil", "consulta")]


def _contrasena() -> str:
    return secrets.token_urlsafe(9) + "-7"


def crear_piloto(srv: Servidor, carpeta: Path, anio: int, mes: int, admin_usuario: str = "piloto.admin") -> list[str]:
    from sqlalchemy import select
    from .modelo import Empresa, Usuario
    salida, claves = [], {}
    with srv.bd() as s:
        admin = s.scalar(select(Usuario).where(Usuario.admin_aeros.is_(True)))
        empresa = s.scalar(select(Empresa).where(Empresa.clave == "piloto"))
    if admin is None:
        claves[admin_usuario] = _contrasena()
        admin = srv.crear_admin(admin_usuario, claves[admin_usuario])
    if empresa is None:
        empresa = srv.crear_empresa(admin, "piloto", "Empresa piloto (ficticia)", "base")
    base = next((b for b in empresa.bases if b.codigo == "PIL"), None) or \
        srv.crear_base(admin, empresa.id, "PIL", "Base piloto")
    existentes = {u.usuario: u for u in srv.usuarios(admin)}
    for usuario, rol in CUENTAS:
        if usuario in existentes:
            continue
        claves[usuario] = _contrasena()
        u = srv.crear_usuario(admin, usuario, claves[usuario], empresa.id, central=rol is None)
        if rol:
            srv.dar_acceso(admin, u.id, base.id, rol)
    central = srv.usuario_de(srv.entrar("central.piloto", claves["central.piloto"])) if "central.piloto" in claves \
        else None
    if central is None:
        salida.append("La empresa piloto ya existía: no se cambian sus datos.")
        return salida

    conf = Configuracion.cargar(RAIZ / "config" / "base.yaml")
    base = srv.base(central, base.id)
    destino = srv.carpeta_base(central, base)
    arch = Archivo(destino / "archivo")
    cuadrantes = sorted(carpeta.glob("cuadrante_ficticio_*.xlsx"))
    if not cuadrantes:
        raise ErrorDatos(f"No hay cuadrante_ficticio_AAAA-MM.xlsx en {carpeta}.")
    for ruta in cuadrantes:
        a_, m_ = map(int, ruta.stem.rsplit("_", 1)[1].split("-"))
        filas = leer_cuadrante(ruta, a_)
        arch.guardar_cuadrante(a_, m_, filas, "real")
    arch.guardar_contratos(leer_contratos(carpeta / "contratos_ficticios.xlsx"))
    arch.guardar_formacion(leer_habilitaciones(carpeta / "formacion_ficticia.xlsx", conf))
    Almacen(destino / "registro").guardar_plantilla(filas)
    vuelos = RAIZ / "ejemplos" / "demo" / "vuelos_noviembre_2026.xlsx"
    if (anio, mes) == (2026, 11) and vuelos.exists():
        arch.guardar_vuelos(anio, mes, {d: leer_vuelos(vuelos, d, conf.zona_horaria)[0] for d in dias_del_mes(anio, mes)})
    srv.guardar_personal(central, base, fichas_de_la_base(arch, conf))
    salida.append(f"Base PIL: {len(filas)} personas ficticias, cuadrantes de {len(cuadrantes)} meses.")
    salida.append("Cuentas creadas (apunta las contraseñas, no se vuelven a mostrar):")
    salida += [f"  {u}: {c}" for u, c in claves.items()]
    return salida
