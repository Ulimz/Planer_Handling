"""Todo lo que se hace en el servidor pasa por aquí: cada operación comprueba quién la pide y lo
apunta en el registro. Las pantallas (web) solo llaman a estas funciones."""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from . import permisos
from .modelo import Acceso, Apunte, Base, Empresa, Persona, Sesion, Tabla, Usuario, ahora
from .permisos import SinPermiso
from .seguridad import comprobar_contrasena, hash_contrasena, huella, nuevo_token, problema_contrasena

FALLOS_MAXIMOS = 5
BLOQUEO = timedelta(minutes=15)
DURACION_SESION = timedelta(hours=10)
CLAVE = re.compile(r"^[a-z0-9_]{2,40}$")
CODIGO_BASE = re.compile(r"^[A-Z0-9]{2,10}$")
USUARIO = re.compile(r"^[a-z0-9._-]{3,80}$")


class ErrorDatos(ValueError):
    pass


class Servidor:
    def __init__(self, url_bd: str, carpeta_datos: str | Path):
        self.motor = create_engine(url_bd, future=True)
        self.fabrica = sessionmaker(self.motor, expire_on_commit=False)
        self.carpeta = Path(carpeta_datos)

    def crear_tablas(self) -> None:
        Tabla.metadata.create_all(self.motor)

    @contextmanager
    def bd(self) -> Session:
        s = self.fabrica()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # --- registro -----------------------------------------------------------------------------
    @staticmethod
    def _apuntar(s: Session, actor: Usuario | None, accion: str, detalle: str = "", empresa_id: int | None = None,
                 base_id: int | None = None) -> None:
        s.add(Apunte(usuario_id=actor.id if actor else None,
                     empresa_id=empresa_id if empresa_id is not None else (actor.empresa_id if actor else None),
                     base_id=base_id, accion=accion, detalle=detalle))

    def apuntar(self, actor: Usuario, accion: str, detalle: str = "", base: Base | None = None) -> None:
        with self.bd() as s:
            self._apuntar(s, actor, accion, detalle, base.empresa_id if base else None, base.id if base else None)

    def registro(self, actor: Usuario, limite: int = 200) -> list[Apunte]:
        """Lo apuntado: el administrador de AEROS ve todo; la central, solo su empresa."""
        with self.bd() as s:
            q = select(Apunte).order_by(Apunte.id.desc()).limit(limite)
            if actor.admin_aeros:
                return list(s.scalars(q))
            if not permisos.gestiona_usuarios(actor):
                raise SinPermiso("Solo la central ve el registro.")
            return list(s.scalars(q.where(Apunte.empresa_id == actor.empresa_id)))

    # --- entrar y salir ------------------------------------------------------------------------
    def crear_admin(self, usuario: str, contrasena: str) -> Usuario:
        """Primer usuario del servidor (se hace una vez, desde la consola del servidor)."""
        self._validar_usuario(usuario, contrasena)
        with self.bd() as s:
            if s.scalar(select(Usuario).where(Usuario.usuario == usuario)):
                raise ErrorDatos(f"Ya existe el usuario {usuario}.")
            u = Usuario(usuario=usuario, hash=hash_contrasena(contrasena), admin_aeros=True)
            s.add(u)
            s.flush()
            self._apuntar(s, u, "crear_admin", usuario)
            return u

    def entrar(self, usuario: str, contrasena: str) -> str:
        """Token de sesión. El mismo mensaje si el usuario no existe o la contraseña está mal."""
        mal = ErrorDatos("Usuario o contraseña incorrectos.")
        with self.bd() as s:
            u = s.scalar(select(Usuario).where(Usuario.usuario == usuario.strip().lower()))
            if u is None or not u.activo:
                raise mal
            if u.bloqueado_hasta and u.bloqueado_hasta > ahora():
                raise ErrorDatos("Demasiados intentos. Prueba otra vez dentro de 15 minutos.")
            if not comprobar_contrasena(contrasena, u.hash):
                u.fallos += 1
                if u.fallos >= FALLOS_MAXIMOS:
                    u.fallos, u.bloqueado_hasta = 0, ahora() + BLOQUEO
                    self._apuntar(s, u, "bloqueo", "demasiados intentos")
                s.commit()          # el fallo se guarda aunque se avise del error
                raise mal
            u.fallos, u.bloqueado_hasta = 0, None
            token = nuevo_token()
            s.add(Sesion(huella=huella(token), usuario_id=u.id, caduca=ahora() + DURACION_SESION))
            self._apuntar(s, u, "entrar")
            return token

    def usuario_de(self, token: str | None) -> Usuario | None:
        if not token:
            return None
        with self.bd() as s:
            sesion = s.scalar(select(Sesion).where(Sesion.huella == huella(token)))
            if sesion is None or sesion.caduca < ahora() or not sesion.usuario.activo:
                return None
            u = sesion.usuario
            _ = [a.base.empresa for a in u.accesos], u.empresa
            return u

    def salir(self, token: str) -> None:
        with self.bd() as s:
            sesion = s.scalar(select(Sesion).where(Sesion.huella == huella(token)))
            if sesion:
                self._apuntar(s, sesion.usuario, "salir")
                s.delete(sesion)

    def cambiar_contrasena(self, actor: Usuario, actual: str, nueva: str) -> None:
        with self.bd() as s:
            u = s.get(Usuario, actor.id)
            if not comprobar_contrasena(actual, u.hash):
                raise ErrorDatos("La contraseña actual no es correcta.")
            self._validar_usuario(u.usuario, nueva)
            u.hash = hash_contrasena(nueva)
            for sesion in s.scalars(select(Sesion).where(Sesion.usuario_id == u.id)):
                s.delete(sesion)
            self._apuntar(s, u, "cambiar_contrasena")

    @staticmethod
    def _validar_usuario(usuario: str, contrasena: str) -> None:
        if not USUARIO.match(usuario):
            raise ErrorDatos("El usuario solo puede llevar minúsculas, números, punto, guion y guion bajo "
                             "(de 3 a 80).")
        if (problema := problema_contrasena(contrasena, usuario)):
            raise ErrorDatos(problema)

    # --- panel de AEROS: empresas y bases --------------------------------------------------------
    @staticmethod
    def _solo_admin(actor: Usuario) -> None:
        if not (actor.activo and actor.admin_aeros):
            raise SinPermiso("Solo el administrador de AEROS.")

    def crear_empresa(self, actor: Usuario, clave: str, nombre: str, perfil: str = "base") -> Empresa:
        self._solo_admin(actor)
        if not CLAVE.match(clave):
            raise ErrorDatos("La clave de la empresa: minúsculas, números y guion bajo (por ejemplo, jet2).")
        with self.bd() as s:
            if s.scalar(select(Empresa).where(Empresa.clave == clave)):
                raise ErrorDatos(f"Ya existe la empresa {clave}.")
            e = Empresa(clave=clave, nombre=nombre.strip() or clave, perfil=perfil)
            s.add(e)
            s.flush()
            self._apuntar(s, actor, "crear_empresa", f"{clave} ({nombre})", e.id)
            s.refresh(e)
            _ = e.bases
            return e

    def activar_empresa(self, actor: Usuario, empresa_id: int, activa: bool) -> None:
        self._solo_admin(actor)
        with self.bd() as s:
            e = s.get(Empresa, empresa_id)
            e.activa = activa
            self._apuntar(s, actor, "activar_empresa" if activa else "bloquear_empresa", e.clave, e.id)

    def crear_base(self, actor: Usuario, empresa_id: int, codigo: str, nombre: str = "",
                   herramientas: list[str] | None = None) -> Base:
        self._solo_admin(actor)
        codigo = codigo.strip().upper()
        if not CODIGO_BASE.match(codigo):
            raise ErrorDatos("El código de la base: letras y números, por ejemplo ALC.")
        herramientas = self._herramientas_validas(herramientas if herramientas is not None else permisos.TODAS)
        with self.bd() as s:
            e = s.get(Empresa, empresa_id)
            if any(b.codigo == codigo for b in e.bases):
                raise ErrorDatos(f"{e.nombre} ya tiene la base {codigo}.")
            b = Base(empresa_id=e.id, codigo=codigo, nombre=nombre.strip(), herramientas=herramientas)
            s.add(b)
            s.flush()
            self._apuntar(s, actor, "crear_base", f"{codigo}: {', '.join(herramientas)}", e.id, b.id)
            s.refresh(b)
            _ = b.empresa
            return b

    def cambiar_base(self, actor: Usuario, base_id: int, herramientas: list[str] | None = None,
                     activa: bool | None = None) -> None:
        self._solo_admin(actor)
        with self.bd() as s:
            b = s.get(Base, base_id)
            if herramientas is not None:
                b.herramientas = self._herramientas_validas(herramientas)
            if activa is not None:
                b.activa = activa
            self._apuntar(s, actor, "cambiar_base",
                          f"{b.codigo}: {', '.join(b.herramientas)}{'' if b.activa else ' (bloqueada)'}",
                          b.empresa_id, b.id)

    @staticmethod
    def _herramientas_validas(herramientas: list[str]) -> list[str]:
        malas = [h for h in herramientas if h not in permisos.HERRAMIENTAS]
        if malas:
            raise ErrorDatos(f"Herramientas que no existen: {', '.join(malas)}.")
        return [h for h in permisos.TODAS if h in herramientas]

    def empresas(self, actor: Usuario) -> list[Empresa]:
        self._solo_admin(actor)
        with self.bd() as s:
            return list(s.scalars(select(Empresa).order_by(Empresa.nombre)))

    # --- usuarios y accesos (la central de cada empresa) -------------------------------------------
    def crear_usuario(self, actor: Usuario, usuario: str, contrasena: str, empresa_id: int | None = None,
                      central: bool = False) -> Usuario:
        """El administrador de AEROS crea la primera cuenta de la central de una empresa; la central crea
        el resto de cuentas de su empresa."""
        usuario = usuario.strip().lower()
        if actor.admin_aeros:
            if empresa_id is None:
                raise ErrorDatos("Falta la empresa.")
        elif permisos.gestiona_usuarios(actor):
            empresa_id = actor.empresa_id
        else:
            raise SinPermiso("Solo la central crea usuarios.")
        self._validar_usuario(usuario, contrasena)
        with self.bd() as s:
            if s.scalar(select(Usuario).where(Usuario.usuario == usuario)):
                raise ErrorDatos(f"Ya existe el usuario {usuario}.")
            u = Usuario(usuario=usuario, hash=hash_contrasena(contrasena), empresa_id=empresa_id, central=central)
            s.add(u)
            s.flush()
            self._apuntar(s, actor, "crear_usuario", f"{usuario}{' (central)' if central else ''}", empresa_id)
            s.refresh(u)
            _ = u.accesos, u.empresa
            return u

    def _usuario_de_mi_empresa(self, s: Session, actor: Usuario, usuario_id: int) -> Usuario:
        u = s.get(Usuario, usuario_id)
        if u is None or u.admin_aeros or not (actor.admin_aeros or
                                               (permisos.gestiona_usuarios(actor) and u.empresa_id == actor.empresa_id)):
            raise SinPermiso("Ese usuario no es de tu empresa.")
        return u

    def dar_acceso(self, actor: Usuario, usuario_id: int, base_id: int, rol: str,
                   herramientas: list[str] | None = None) -> None:
        if rol not in permisos.ROLES:
            raise ErrorDatos(f"Rol desconocido: {rol}.")
        if herramientas is not None:
            herramientas = self._herramientas_validas(herramientas)
        with self.bd() as s:
            u = self._usuario_de_mi_empresa(s, actor, usuario_id)
            b = s.get(Base, base_id)
            if b is None or b.empresa_id != u.empresa_id:
                raise SinPermiso("Esa base no es de la empresa del usuario.")
            acceso = next((a for a in u.accesos if a.base_id == b.id), None)
            if acceso is None:
                acceso = Acceso(usuario_id=u.id, base_id=b.id, rol=rol)
                s.add(acceso)
            acceso.rol, acceso.herramientas = rol, herramientas
            self._apuntar(s, actor, "dar_acceso", f"{u.usuario} en {b.codigo}: {permisos.ROLES[rol]}"
                          + (f" ({', '.join(herramientas)})" if herramientas is not None else ""), b.empresa_id, b.id)

    def quitar_acceso(self, actor: Usuario, usuario_id: int, base_id: int) -> None:
        with self.bd() as s:
            u = self._usuario_de_mi_empresa(s, actor, usuario_id)
            for a in list(u.accesos):
                if a.base_id == base_id:
                    u.accesos.remove(a)
                    self._apuntar(s, actor, "quitar_acceso", f"{u.usuario} en {a.base.codigo}", u.empresa_id, base_id)

    def activar_usuario(self, actor: Usuario, usuario_id: int, activo: bool) -> None:
        with self.bd() as s:
            u = self._usuario_de_mi_empresa(s, actor, usuario_id)
            if u.id == actor.id and not activo:
                raise ErrorDatos("No puedes desactivar tu propia cuenta.")
            u.activo = activo
            if not activo:
                for sesion in s.scalars(select(Sesion).where(Sesion.usuario_id == u.id)):
                    s.delete(sesion)
            self._apuntar(s, actor, "activar_usuario" if activo else "desactivar_usuario", u.usuario, u.empresa_id)

    def poner_contrasena(self, actor: Usuario, usuario_id: int, contrasena: str) -> None:
        """La central pone una contraseña nueva a quien la ha olvidado."""
        with self.bd() as s:
            u = self._usuario_de_mi_empresa(s, actor, usuario_id)
            self._validar_usuario(u.usuario, contrasena)
            u.hash, u.fallos, u.bloqueado_hasta = hash_contrasena(contrasena), 0, None
            for sesion in s.scalars(select(Sesion).where(Sesion.usuario_id == u.id)):
                s.delete(sesion)
            self._apuntar(s, actor, "poner_contrasena", u.usuario, u.empresa_id)

    def usuarios(self, actor: Usuario) -> list[Usuario]:
        with self.bd() as s:
            q = select(Usuario).where(Usuario.admin_aeros.is_(False)).order_by(Usuario.usuario)
            if actor.admin_aeros:
                return list(s.scalars(q))
            if not permisos.gestiona_usuarios(actor):
                raise SinPermiso("Solo la central ve los usuarios.")
            return list(s.scalars(q.where(Usuario.empresa_id == actor.empresa_id)))

    # --- bases y sus datos ---------------------------------------------------------------------
    def bases_visibles(self, actor: Usuario) -> list[Base]:
        if actor.admin_aeros or actor.empresa_id is None:
            return []
        with self.bd() as s:
            todas = s.scalars(select(Base).where(Base.empresa_id == actor.empresa_id).order_by(Base.codigo))
            return [b for b in todas if permisos.ve_base(actor, b)]

    def base(self, actor: Usuario, base_id: int) -> Base:
        with self.bd() as s:
            b = s.get(Base, base_id)
            if b is None or not permisos.ve_base(actor, b):
                raise SinPermiso("No tienes acceso a esa base.")
            return b

    def carpeta_empresa(self, empresa: Empresa) -> Path:
        return self.carpeta / empresa.clave

    def carpeta_base(self, actor: Usuario, base: Base) -> Path:
        """Donde se guardan los datos de la base (cuadrantes, vuelos, ausencias…), solo con códigos."""
        if not permisos.ve_base(actor, base):
            raise SinPermiso("No tienes acceso a esa base.")
        return self.carpeta_empresa(base.empresa) / "bases" / base.codigo

    # --- personal ------------------------------------------------------------------------------
    def guardar_personal(self, actor: Usuario, base: Base, fichas: list[dict]) -> int:
        """Sustituye las fichas de la base por las nuevas (salen del último cuadrante real)."""
        permisos.exigir(actor, base, "datos", cambiar=True)
        with self.bd() as s:
            for p in s.scalars(select(Persona).where(Persona.base_id == base.id)):
                s.delete(p)
            s.flush()
            for f in fichas:
                s.add(Persona(base_id=base.id, **f))
            self._apuntar(s, actor, "guardar_personal", f"{len(fichas)} personas", base.empresa_id, base.id)
        return len(fichas)

    def personal(self, actor: Usuario, base_ids: list[int] | None = None) -> list[Persona]:
        """Fichas de las bases que el usuario puede ver con la herramienta «personal»."""
        bases = [b for b in self.bases_visibles(actor) if permisos.puede(actor, b, "personal")
                 and (base_ids is None or b.id in base_ids)]
        if not bases:
            return []
        with self.bd() as s:
            return list(s.scalars(select(Persona).where(Persona.base_id.in_([b.id for b in bases]))
                                  .order_by(Persona.base_id, Persona.codigo)))

