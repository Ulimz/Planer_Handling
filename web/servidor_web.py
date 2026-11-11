"""Pantallas del modo servidor: entrar, elegir base, panel de AEROS, usuarios de la central y personal.

Se activa con AEROS_SERVIDOR=1. Sin esa variable la web funciona como siempre, en el ordenador."""
from __future__ import annotations

import streamlit as st

from planer_handling.servidor.cli import servidor as _servidor
from planer_handling.servidor.permisos import HERRAMIENTAS, ROLES, SinPermiso
from planer_handling.servidor.personal import Filtro, estado_del_dia, filtrar
from planer_handling.servidor.servicio import ErrorDatos


@st.cache_resource
def srv():
    return _servidor()


def _error(e: Exception) -> None:
    st.error(str(e))


def usuario_actual():
    """El usuario que ha entrado, o la pantalla de entrada (y se para aquí)."""
    u = srv().usuario_de(st.session_state.get("token"))
    if u is not None:
        return u
    st.session_state.pop("token", None)
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro, st.form("entrar"):
        st.subheader("Entrar en AEROS")
        usuario = st.text_input("Usuario")
        contrasena = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary", width="stretch"):
            try:
                st.session_state["token"] = srv().entrar(usuario, contrasena)
                st.rerun()
            except ErrorDatos as e:
                _error(e)
    st.stop()


def barra(u) -> object | None:
    """Barra lateral: quién es, qué base trabaja, cambiar contraseña y salir. Devuelve la base elegida."""
    st.sidebar.markdown(f"**{u.usuario}**  \n"
                        + ("Administrador de AEROS" if u.admin_aeros else
                           f"{u.empresa.nombre} · {'central' if u.central else 'base'}"))
    base = None
    if not u.admin_aeros:
        bases = srv().bases_visibles(u)
        if bases:
            ids = [b.id for b in bases]
            elegida = st.sidebar.selectbox("Base", ids, key="base_id",
                                           format_func=lambda i: next(f"{b.codigo} {b.nombre}".strip()
                                                                      for b in bases if b.id == i))
            base = next(b for b in bases if b.id == elegida)
        else:
            st.sidebar.warning("No tienes ninguna base. Pide acceso a la central de tu empresa.")
    with st.sidebar.expander("Cambiar mi contraseña"):
        with st.form("contrasena", clear_on_submit=True):
            actual = st.text_input("Actual", type="password")
            nueva = st.text_input("Nueva (10 caracteres o más)", type="password")
            if st.form_submit_button("Cambiar"):
                try:
                    srv().cambiar_contrasena(u, actual, nueva)
                    st.session_state.pop("token", None)
                    st.rerun()
                except ErrorDatos as e:
                    st.error(str(e))
    if st.sidebar.button("Salir"):
        srv().salir(st.session_state.pop("token", ""))
        st.rerun()
    return base


# --- panel de AEROS (nosotros) ------------------------------------------------------------------
def panel_admin(u, perfiles_ejemplo: list[str]) -> None:
    st.subheader("Panel de AEROS")
    st.caption("Aquí se dan de alta las empresas, se activan sus bases y las herramientas que tienen "
               "contratadas, y se crea la primera cuenta de la central de cada empresa. Desde aquí no se ven "
               "los cuadrantes ni el personal de las bases.")
    empresas = srv().empresas(u)
    for e in empresas:
        with st.expander(f"{e.nombre} ({e.clave}){'' if e.activa else ' · BLOQUEADA'}", expanded=False):
            c1, c2 = st.columns([3, 1])
            c1.caption(f"Reglas de partida: {e.perfil}. Bases: {', '.join(b.codigo for b in e.bases) or 'ninguna'}.")
            if c2.button("Desbloquear" if not e.activa else "Bloquear", key=f"act_{e.id}"):
                srv().activar_empresa(u, e.id, not e.activa)
                st.rerun()
            for b in e.bases:
                cc = st.columns([1, 4, 1])
                cc[0].markdown(f"**{b.codigo}**" + ("" if b.activa else " (bloqueada)"))
                nuevas = cc[1].multiselect("Herramientas", list(HERRAMIENTAS), b.herramientas, key=f"h_{b.id}",
                                           format_func=HERRAMIENTAS.get, label_visibility="collapsed")
                if nuevas != b.herramientas and cc[2].button("Guardar", key=f"gh_{b.id}"):
                    srv().cambiar_base(u, b.id, herramientas=nuevas)
                    st.rerun()
                if cc[2].button("Desbloquear" if not b.activa else "Bloquear", key=f"bb_{b.id}"):
                    srv().cambiar_base(u, b.id, activa=not b.activa)
                    st.rerun()
            with st.form(f"base_{e.id}", clear_on_submit=True):
                st.markdown("Nueva base")
                c1, c2 = st.columns([1, 3])
                codigo = c1.text_input("Código", placeholder="ALC", key=f"cb_{e.id}")
                nombre = c2.text_input("Nombre", placeholder="Alicante", key=f"nb_{e.id}")
                herr = st.multiselect("Herramientas contratadas", list(HERRAMIENTAS), list(HERRAMIENTAS),
                                      format_func=HERRAMIENTAS.get, key=f"hb_{e.id}")
                if st.form_submit_button("Crear base"):
                    try:
                        srv().crear_base(u, e.id, codigo, nombre, herr)
                        st.rerun()
                    except ErrorDatos as x:
                        st.error(str(x))
            with st.form(f"central_{e.id}", clear_on_submit=True):
                st.markdown("Cuenta de la central de esta empresa")
                c1, c2 = st.columns(2)
                usuario = c1.text_input("Usuario", key=f"uc_{e.id}")
                contrasena = c2.text_input("Contraseña inicial", type="password", key=f"pc_{e.id}")
                if st.form_submit_button("Crear cuenta"):
                    try:
                        srv().crear_usuario(u, usuario, contrasena, e.id, central=True)
                        st.success(f"Cuenta {usuario} creada. Pásale la contraseña por un canal seguro.")
                    except ErrorDatos as x:
                        st.error(str(x))
    with st.form("empresa", clear_on_submit=True):
        st.markdown("#### Nueva empresa")
        c1, c2, c3 = st.columns(3)
        clave = c1.text_input("Clave", placeholder="jet2")
        nombre = c2.text_input("Nombre", placeholder="Jet2")
        perfil = c3.selectbox("Reglas de partida", perfiles_ejemplo)
        if st.form_submit_button("Crear empresa", type="primary"):
            try:
                srv().crear_empresa(u, clave.strip().lower(), nombre, perfil)
                st.rerun()
            except ErrorDatos as x:
                st.error(str(x))
    _registro(u)


def _registro(u) -> None:
    with st.expander("Registro (quién hizo qué)"):
        nombres = {x.id: x.usuario for x in srv().usuarios(u)}
        nombres[u.id] = u.usuario
        st.dataframe([{"Fecha (UTC)": f"{a.fecha:%d/%m/%Y %H:%M}", "Usuario": nombres.get(a.usuario_id, "—"),
                       "Qué": a.accion, "Detalle": a.detalle} for a in srv().registro(u)],
                     hide_index=True, width="stretch")


# --- la central: usuarios y permisos ----------------------------------------------------------
def panel_central(u) -> None:
    st.subheader("Usuarios y permisos")
    st.caption("Cada usuario ve solo las bases que le des aquí, con su rol y, si quieres, solo algunas "
               "herramientas. Los cambios valen al momento.")
    bases = srv().bases_visibles(u)
    por_id = {b.id: b for b in bases}
    usuarios = srv().usuarios(u)
    st.dataframe([{"Usuario": x.usuario, "Activo": "sí" if x.activo else "no",
                   "Central": "sí" if x.central else "",
                   "Bases": "todas" if x.central else "; ".join(
                       f"{a.base.codigo}: {ROLES[a.rol]}" + (f" ({', '.join(a.herramientas)})" if a.herramientas else "")
                       for a in x.accesos)} for x in usuarios], hide_index=True, width="stretch")

    c1, c2 = st.columns(2)
    with c1.form("nuevo_usuario", clear_on_submit=True):
        st.markdown("**Nuevo usuario**")
        nombre = st.text_input("Usuario", placeholder="jefe.alc", help="Mejor un nombre de puesto, no de persona.")
        contrasena = st.text_input("Contraseña inicial", type="password")
        central = st.checkbox("Es de la central (ve y cambia todas las bases)")
        if st.form_submit_button("Crear", type="primary"):
            try:
                srv().crear_usuario(u, nombre, contrasena, central=central)
                st.rerun()
            except (ErrorDatos, SinPermiso) as e:
                st.error(str(e))
    otros = [x for x in usuarios if not x.central]
    with c2.form("acceso"):
        st.markdown("**Dar o cambiar acceso a una base**")
        if not (otros and bases):
            st.caption("Hace falta un usuario que no sea de la central y una base.")
        quien = st.selectbox("Usuario", [x.id for x in otros], format_func=lambda i: next(x.usuario for x in otros if x.id == i))
        donde = st.selectbox("Base", list(por_id), format_func=lambda i: por_id[i].codigo)
        rol = st.selectbox("Rol", list(ROLES), format_func=ROLES.get)
        solo = st.multiselect("Solo estas herramientas (vacío = todas las de la base)",
                              por_id[donde].herramientas if donde else [], format_func=HERRAMIENTAS.get)
        a1, a2 = st.columns(2)
        if a1.form_submit_button("Guardar acceso", type="primary", disabled=not (quien and donde)):
            try:
                srv().dar_acceso(u, quien, donde, rol, solo or None)
                st.rerun()
            except (ErrorDatos, SinPermiso) as e:
                st.error(str(e))
        if a2.form_submit_button("Quitar acceso", disabled=not (quien and donde)):
            srv().quitar_acceso(u, quien, donde)
            st.rerun()
    with st.expander("Desactivar un usuario o ponerle contraseña nueva"):
        cuentas = [x for x in usuarios if x.id != u.id]
        if cuentas:
            c1, c2, c3 = st.columns([2, 2, 1])
            quien = c1.selectbox("Usuario", [x.id for x in cuentas], key="gest_u",
                                 format_func=lambda i: next(x.usuario for x in cuentas if x.id == i))
            x = next(c for c in cuentas if c.id == quien)
            nueva = c2.text_input("Contraseña nueva", type="password", key="gest_p")
            if c3.button("Poner contraseña", disabled=not nueva):
                try:
                    srv().poner_contrasena(u, quien, nueva)
                    st.success("Hecho. Se han cerrado sus sesiones abiertas.")
                except ErrorDatos as e:
                    st.error(str(e))
            if c3.button("Activar" if not x.activo else "Desactivar"):
                srv().activar_usuario(u, quien, not x.activo)
                st.rerun()
    _registro(u)


# --- personal -------------------------------------------------------------------------------
def pagina_personal(u, archivo_de, colores: dict[str, str]) -> None:
    """`archivo_de(base)` -> Archivo de esa base (para ver si trabaja un día)."""
    st.subheader("Personal")
    st.caption("Solo códigos: el programa organiza con la función, las capacitaciones, el contrato y la "
               "rotación de cada uno. Las fichas salen del último cuadrante real subido en Datos.")
    personas = srv().personal(u)
    if not personas:
        st.info("Aún no hay fichas. Sube un cuadrante real en la pestaña Datos.")
        return
    base_de = lambda p: p.base.codigo  # noqa: E731
    valores = lambda campo: sorted({getattr(p, campo) for p in personas if getattr(p, campo)})  # noqa: E731
    c = st.columns(5)
    bases = c[0].multiselect("Base", sorted({base_de(p) for p in personas}), placeholder="Todas")
    funciones = c[1].multiselect("Función", valores("funcion"), placeholder="Todas")
    capacit = c[2].multiselect("Con estas capacitaciones", sorted({h for p in personas for h in p.capacitaciones}),
                               placeholder="Cualquiera")
    contratos = c[3].multiselect("Contrato", valores("contrato"), placeholder="Todas")
    rotaciones = c[4].multiselect("Rotación", valores("rotacion"), placeholder="Todas")
    c1, c2 = st.columns([1, 1])
    texto = c1.text_input("Código", placeholder="P00")
    dia = c2.date_input("Cómo está el día", None, format="DD/MM/YYYY",
                        help="Mira si cada uno trabaja o libra ese día: primero en el cuadrante guardado, y si no "
                             "lo hay, por su rotación.")
    elegidas = filtrar(personas, Filtro(bases or None, funciones or None, capacit or None, contratos or None,
                                        rotaciones or None, texto), base_de)
    archivos = {}
    filas = []
    for p in elegidas:
        fila = {"Base": base_de(p), "Código": p.codigo, "Función": p.funcion, "Contrato": p.contrato,
                "Rotación": p.rotacion, "Capacitaciones": ", ".join(p.capacitaciones)}
        if dia:
            if p.base_id not in archivos:
                archivos[p.base_id] = archivo_de(p.base)
            fila[f"{dia:%d/%m}"] = estado_del_dia(p, dia, archivos[p.base_id], colores)
        filas.append(fila)
    if dia:
        libres = sum(1 for f in filas if f[f"{dia:%d/%m}"].startswith("Libra"))
        st.caption(f"{len(filas)} personas; {libres} libran el {dia:%d/%m/%Y}.")
    else:
        st.caption(f"{len(filas)} de {len(personas)} personas.")
    st.dataframe(filas, hide_index=True, width="stretch")
