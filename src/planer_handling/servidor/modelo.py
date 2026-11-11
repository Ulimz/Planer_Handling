"""Tablas de la base de datos del servidor (SQLite en pruebas, PostgreSQL en el servidor)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tabla(DeclarativeBase):
    pass


class Empresa(Tabla):
    """Un cliente de AEROS (una empresa de handling). Se da de alta desde el panel de AEROS."""
    __tablename__ = "empresas"
    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(40), unique=True)          # "jet2", carpeta de sus datos
    nombre: Mapped[str] = mapped_column(String(120))
    perfil: Mapped[str] = mapped_column(String(80), default="base")      # perfil de ejemplo del que parte
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creada: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    bases: Mapped[list["Base"]] = relationship(back_populates="empresa", order_by="Base.codigo", lazy="selectin")


class Base(Tabla):
    """Un aeropuerto de una empresa, con las herramientas que tiene contratadas."""
    __tablename__ = "bases"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    codigo: Mapped[str] = mapped_column(String(10))                      # "ALC"
    nombre: Mapped[str] = mapped_column(String(120), default="")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    herramientas: Mapped[list] = mapped_column(JSON, default=list)
    empresa: Mapped[Empresa] = relationship(back_populates="bases", lazy="selectin")


class Usuario(Tabla):
    """Quien entra en AEROS. Sin empresa = administrador de AEROS (nosotros)."""
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario: Mapped[str] = mapped_column(String(80), unique=True)
    hash: Mapped[str] = mapped_column(String(200))
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresas.id"), nullable=True)
    admin_aeros: Mapped[bool] = mapped_column(Boolean, default=False)
    central: Mapped[bool] = mapped_column(Boolean, default=False)        # la central de su empresa: todas sus bases
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    fallos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    empresa: Mapped[Empresa | None] = relationship(lazy="selectin")
    accesos: Mapped[list["Acceso"]] = relationship(back_populates="usuario", cascade="all, delete-orphan",
                                                    lazy="selectin")


class Acceso(Tabla):
    """Qué puede hacer un usuario en una base: su rol allí y, si se quiere, solo algunas herramientas."""
    __tablename__ = "accesos"
    __table_args__ = (UniqueConstraint("usuario_id", "base_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    base_id: Mapped[int] = mapped_column(ForeignKey("bases.id"))
    rol: Mapped[str] = mapped_column(String(20))                         # jefe_base, planificador, consulta
    herramientas: Mapped[list | None] = mapped_column(JSON, nullable=True)   # None: todas las de la base
    usuario: Mapped[Usuario] = relationship(back_populates="accesos")
    base: Mapped[Base] = relationship(lazy="selectin")


class Sesion(Tabla):
    __tablename__ = "sesiones"
    id: Mapped[int] = mapped_column(primary_key=True)
    huella: Mapped[str] = mapped_column(String(64), unique=True)         # sha256 del token, nunca el token
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    caduca: Mapped[datetime] = mapped_column(DateTime)
    usuario: Mapped[Usuario] = relationship()


class Persona(Tabla):
    """Ficha de una persona de una base para buscar y filtrar. Solo código, nunca nombre."""
    __tablename__ = "personal"
    __table_args__ = (UniqueConstraint("base_id", "codigo"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("bases.id"))
    codigo: Mapped[str] = mapped_column(String(20))
    funcion: Mapped[str] = mapped_column(String(40), default="")
    categoria: Mapped[str] = mapped_column(String(40), default="")
    contrato: Mapped[str] = mapped_column(String(20), default="")
    rotacion: Mapped[str] = mapped_column(String(20), default="")       # "6x3", "4x4", "irregular"
    ancla: Mapped[str] = mapped_column(String(10), default="")          # día en la posición 0 del ciclo (ISO)
    fases: Mapped[dict] = mapped_column(JSON, default=dict)             # posición del ciclo -> "M"/"T"
    capacitaciones: Mapped[list] = mapped_column(JSON, default=list)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    base: Mapped[Base] = relationship(lazy="selectin")


class Apunte(Tabla):
    """Registro de quién hizo qué y cuándo (entradas, permisos, datos subidos, cuadrantes guardados)."""
    __tablename__ = "registro"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresas.id"), nullable=True)
    base_id: Mapped[int | None] = mapped_column(ForeignKey("bases.id"), nullable=True)
    accion: Mapped[str] = mapped_column(String(40))
    detalle: Mapped[str] = mapped_column(Text, default="")
