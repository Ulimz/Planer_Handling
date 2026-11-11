"""Consola del servidor: crear las tablas y la cuenta del administrador de AEROS.

  aeros-servidor iniciar
  aeros-servidor crear-admin USUARIO          (pide la contraseña sin mostrarla)
  aeros-servidor piloto CARPETA               (empresa y base de prueba con datos ficticios)

Lee AEROS_BD (por defecto sqlite:///datos/servidor/aeros.db) y AEROS_DATOS (datos/servidor).
"""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path


def servidor():
    from .servicio import Servidor
    raiz = Path(os.environ.get("AEROS_DATOS", "datos/servidor"))
    raiz.mkdir(parents=True, exist_ok=True)
    srv = Servidor(os.environ.get("AEROS_BD", f"sqlite:///{raiz / 'aeros.db'}"), raiz)
    srv.crear_tablas()
    return srv


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Administración del servidor de AEROS")
    sub = p.add_subparsers(dest="orden", required=True)
    sub.add_parser("iniciar", help="crea las tablas si no existen")
    admin = sub.add_parser("crear-admin", help="cuenta del administrador de AEROS")
    admin.add_argument("usuario")
    piloto = sub.add_parser("piloto", help="empresa PILOTO con la base PIL y los datos ficticios de CARPETA")
    piloto.add_argument("carpeta", type=Path)
    piloto.add_argument("--anio", type=int, default=2026)
    piloto.add_argument("--mes", type=int, default=11)
    a = p.parse_args(argv)
    srv = servidor()
    if a.orden == "iniciar":
        print("Tablas listas.")
    elif a.orden == "crear-admin":
        contrasena = getpass.getpass("Contraseña: ")
        if contrasena != getpass.getpass("Repítela: "):
            raise SystemExit("No coinciden.")
        srv.crear_admin(a.usuario, contrasena)
        print(f"Administrador {a.usuario} creado.")
    elif a.orden == "piloto":
        from .piloto import crear_piloto
        for linea in crear_piloto(srv, a.carpeta, a.anio, a.mes):
            print(linea)


if __name__ == "__main__":
    main()
