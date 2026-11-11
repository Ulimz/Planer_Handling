"""Web del planificador. Los archivos se suben una vez (pestaña Datos) y se guardan en este
ordenador solo con códigos de persona; el cuadrante y la parrilla se ven y se corrigen en pantalla.

Arranque: streamlit run web/app.py  (en Windows, doble clic en arrancar_web.bat)
Todo se calcula en este ordenador; los archivos no salen de él.
"""
from __future__ import annotations

import copy
import tempfile
from datetime import date
from pathlib import Path

import altair as alt
import streamlit as st

import pagina_empresa

from planer_handling.anonimizar import Codigos
from planer_handling.anual import rotaciones_recientes
from planer_handling.archivo import (TIPOS, Archivo, desde_tabla, desde_tabla_vuelos, exportar_cuadrante,
                                     filas_desde_plan, tabla, tabla_vuelos)
from planer_handling.anual_excel import exportar_anio
from planer_handling import empresas
from planer_handling.configuracion import Configuracion
from planer_handling.desde_cuadrante import generar_parrilla_cuadrante
from planer_handling.importar.ausencias import leer_ausencias
from planer_handling.importar.contratos import leer_contratos
from planer_handling.importar.habilitaciones import leer_habilitaciones
from planer_handling.importar.cuadrante import leer_cuadrante
from planer_handling.importar.parrilla_real import leer_vuelos_parrilla
from planer_handling.importar.vuelos import leer_vuelos
from planer_handling.mensual import INICIO_MAS_TEMPRANO, aprender_perfiles, dias_del_mes, emparejar_giros, planificar_mes, reorganizar
from planer_handling.mensual_excel import exportar_mes
from planer_handling.modelos import hhmm as hhmm_
from planer_handling import pasaje
from planer_handling.parrilla_excel import exportar
from planer_handling.registro import Almacen, motivos
from planer_handling.resumen import resumir
from planer_handling.validacion import validar_grupos
from planer_handling import vacaciones
from planer_handling.vacaciones_excel import exportar_vacaciones

RAIZ = Path(__file__).resolve().parent.parent
DEMO = RAIZ / "ejemplos" / "demo"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

IMAGENES = Path(__file__).resolve().parent / "imagenes"
NOMBRE = "AEROS-handling"
CIAN, NARANJA = "#5CCBEF", "#F5A65B"      # colores del logo y el de "lo que piden los vuelos"

st.set_page_config(page_title=NOMBRE, page_icon=str(IMAGENES / "icono.png"), layout="wide")
st.logo(str(IMAGENES / "logo.png"), size="large")
st.markdown(f"""
<style>
.block-container {{padding-top: 2.2rem;}}
.marca {{display:flex; align-items:center; gap:1.1rem; margin-bottom:.4rem;}}
.marca img {{width:64px; height:64px; filter: drop-shadow(0 0 14px rgba(92,203,239,.35));}}
.marca h1 {{margin:0; padding:0; font-size:2.3rem; letter-spacing:.02em;
            text-shadow: 0 0 18px rgba(92,203,239,.35);}}
.marca h1 span {{color:{CIAN};}}
.marca p {{margin:.1rem 0 0; color:#8FA6C0;}}
[data-testid="stMetric"] {{background:#1B2A42; border:1px solid #2A3D5C; border-radius:.8rem;
                          padding:1rem 1.2rem; box-shadow: 0 0 0 1px rgba(92,203,239,.05), 0 6px 20px rgba(0,0,0,.25);}}
[data-testid="stMetricValue"] {{color:{CIAN};}}
.stTabs [data-baseweb="tab-list"] {{gap:1.4rem;}}
.stButton button[kind="primary"], .stDownloadButton button {{box-shadow: 0 0 16px rgba(92,203,239,.25);}}
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {{color:#0E1726; font-weight:600;}}
.stButton button:disabled {{color:#6B7F99 !important; box-shadow:none;}}
</style>
<div class="marca">
  <img src="data:image/png;base64,{__import__("base64").b64encode((IMAGENES / "icono.png").read_bytes()).decode()}">
  <div><h1>AEROS<span>-handling</span></h1>
  <p>Rampa y pasaje planificados a partir de los vuelos · todo se calcula en este ordenador</p></div>
</div>""", unsafe_allow_html=True)
demo = st.sidebar.toggle("Demo con una empresa ficticia", value=False)
if demo:
    st.sidebar.caption("Plantilla de 260 personas con código de empleado y un mes de vuelos inventado con la "
                       "forma de una operación vacacional desde Reino Unido. Los archivos ya están cargados: "
                       "solo hay que pulsar los botones.")
    st.info("Modo demo: empresa ficticia. Mes de referencia octubre de 2026, se planifica noviembre de 2026.")


class ArchivoDemo:
    """Hace las veces de un archivo subido, con un archivo de la carpeta de la demo."""

    def __init__(self, ruta: Path):
        self.ruta, self.name = ruta, ruta.name

    def getbuffer(self) -> bytes:
        return self.ruta.read_bytes()


def archivo(etiqueta: str, tipos: list[str], clave: str, de_demo: str | None = None):
    """En modo demo, el archivo de la demo en lugar de pedir que se suba."""
    if demo and de_demo:
        st.text_input(etiqueta, de_demo, disabled=True, key=f"{clave}_demo")
        return ArchivoDemo(DEMO / de_demo)
    return st.file_uploader(etiqueta, type=tipos, key=clave)


@st.cache_resource
def configuracion(ruta: str, version: int = 0) -> Configuracion:
    return Configuracion.cargar(ruta)


def guardar(subido, carpeta: Path) -> Path:
    ruta = carpeta / subido.name
    ruta.write_bytes(subido.getbuffer())
    return ruta


def elegir_mes(etiqueta: str, por_defecto: date, clave: str, en_demo: date | None = None) -> tuple[int, int]:
    if demo and en_demo:
        por_defecto, clave = en_demo, f"{clave}_demo"
    c1, c2 = st.columns(2)
    mes = c1.selectbox(f"{etiqueta}: mes", range(1, 13), index=por_defecto.month - 1,
                       format_func=lambda m: MESES[m - 1], key=f"{clave}_mes")
    anio = c2.number_input(f"{etiqueta}: año", 2020, 2100, por_defecto.year, key=f"{clave}_anio")
    return int(anio), int(mes)




def nombre_mes(anio: int, mes: int) -> str:
    return f"{MESES[mes - 1]} de {anio}"


def numero(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


EJEMPLOS, PROPIAS = RAIZ / "config", RAIZ / "datos" / "empresas"
perfiles = empresas.listar(EJEMPLOS, PROPIAS)
if demo:
    perfil = next(p for p in perfiles if p.clave == "demo")
else:
    if (pendiente := st.session_state.pop("perfil_pendiente", None)):
        st.session_state["perfil_elegido"] = pendiente
    claves = [p.clave for p in perfiles if p.clave != "demo"]
    if st.session_state.get("perfil_elegido") not in claves:
        st.session_state["perfil_elegido"] = "base"
    elegido = st.sidebar.selectbox("Empresa", claves, key="perfil_elegido",
                                   format_func=lambda c: next(p.nombre for p in perfiles if p.clave == c),
                                   help="Reglas, turnos y contratos con los que se planifica. Se cambian en la "
                                        "pestaña Empresa y reglas.")
    perfil = next(p for p in perfiles if p.clave == elegido)
conf = configuracion(str(perfil.ruta), perfil.ruta.stat().st_mtime_ns)
colores = motivos(conf)
DATOS = RAIZ / "datos"
codigos = Codigos(DATOS / ("codigos_demo.json" if demo else "codigos.json"))
arch = Archivo(DATOS / ("archivo_demo" if demo else "archivo"))
almacen = Almacen(DATOS / ("registro_demo" if demo else "registro"))
if not st.session_state.get(f"anonimizado_{demo}"):
    # Lo apuntado antes de usar códigos (plantilla y ausencias con nombre) pasa a códigos.
    almacen.anonimizar(codigos.codigo)
    st.session_state[f"anonimizado_{demo}"] = True
OCTUBRE_DEMO, NOVIEMBRE_DEMO = date(2026, 10, 1), date(2026, 11, 1)


def leer_subido(subido, lector, *args):
    with tempfile.TemporaryDirectory() as tmp:
        return lector(guardar(subido, Path(tmp)), *args)


def cuadrante_subido(subido, anio: int):
    """El cuadrante con códigos en lugar de nombres: los nombres no pasan de aquí."""
    return codigos.filas(leer_subido(subido, leer_cuadrante, anio))


def vuelos_subidos(subido, anio: int, mes: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        ruta = guardar(subido, Path(tmp))
        return {d: leer_vuelos(ruta, d, conf.zona_horaria)[0] for d in dias_del_mes(anio, mes)}


if demo and not arch.meses():
    with st.spinner("Preparando la demo…"):
        arch.guardar_cuadrante(2026, 10, codigos.filas(leer_cuadrante(DEMO / "cuadrante_octubre_2026.xlsx", 2026)))
        arch.guardar_cuadrante(2026, 11, codigos.filas(
            leer_cuadrante(DEMO / "cuadrante_a_mano_noviembre_2026.xlsx", 2026)))
        arch.guardar_vuelos(2026, 11, {d: leer_vuelos(DEMO / "vuelos_noviembre_2026.xlsx", d, conf.zona_horaria)[0]
                                       for d in dias_del_mes(2026, 11)})
        arch.guardar_contratos(codigos.claves(leer_contratos(DEMO / "contratos.xlsx")))
        almacen.guardar_plantilla(arch.cuadrante(2026, 10))


def meses_con(*que: str) -> list[tuple[int, int]]:
    return [(a, m) for a, m, hay in arch.meses() if all(q in hay for q in que)]


def editor_cuadrante(anio: int, mes: int, tipo: str) -> None:
    """El cuadrante guardado en una tabla que se puede corregir. Cada cambio se comprueba al momento
    contra los vuelos del mes (si están guardados) y se guarda con un botón."""
    filas = arch.cuadrante(anio, mes, tipo)
    dias = dias_del_mes(anio, mes)
    base = tabla(filas, dias, colores)
    clave = f"editor_{demo}_{tipo}_{anio}_{mes}"
    configuracion_columnas = {"Código": st.column_config.TextColumn(pinned=True, width="small"),
                              "Función": st.column_config.TextColumn(width=80)}
    for d in dias:
        configuracion_columnas[f"{d.day:02d}"] = st.column_config.TextColumn(f"{d.day:02d} {'LMXJVSD'[d.weekday()]}",
                                                                             width="small")
    editado = st.data_editor(base, key=clave, hide_index=True, num_rows="dynamic", height=430,
                             column_config=configuracion_columnas, width="stretch")
    errores: list[str] = []
    nuevas = desde_tabla(editado, dias, colores, errores)
    cambiado = editado != base
    if errores:
        st.error("No se entienden estas celdas (se toman como libre hasta que las corrijas): " + "; ".join(errores[:12])
                 + (f" y {len(errores) - 12} más." if len(errores) > 12 else "."))
    vuelos = arch.vuelos(anio, mes)
    if vuelos:
        antes = resumir(filas, vuelos, conf, dias)
        ahora = resumir(nuevas, vuelos, conf, dias) if cambiado else antes
        sin_antes, sin_ahora = sum(r.sin_cubrir for r in antes), sum(r.sin_cubrir for r in ahora)
        c1, c2, c3 = st.columns(3)
        c1.metric("Horas en el cuadrante", numero(sum(r.horas for r in ahora)),
                  f"{numero(sum(r.horas for r in ahora) - sum(r.horas for r in antes))} h con tus cambios"
                  if cambiado else None, delta_color="off")
        c2.metric("Horas sin cubrir", numero(sin_ahora),
                  f"{sin_ahora - sin_antes:+.1f} h con tus cambios".replace(".", ",") if cambiado else None, delta_color="inverse")
        c3.metric("Días con huecos", sum(1 for r in ahora if r.sin_cubrir >= 0.25))
        dif = {a.dia: (a, b) for a, b in zip(antes, ahora)}
        empeoran = [d for d, (a, b) in dif.items() if b.sin_cubrir > a.sin_cubrir + 0.01]
        if cambiado and empeoran:
            st.warning("Con tus cambios quedan más huecos el " + ", ".join(f"{d:%d/%m}" for d in empeoran)
                       + ". Mira el detalle abajo.")
        with st.expander("Huecos día a día", expanded=bool(cambiado and empeoran)):
            filas_h = []
            for r in ahora:
                faltan = {rol: r.plan.deficit(rol) / 60 for rol in r.plan.demanda if r.plan.deficit(rol)}
                franjas = [k for rol in r.plan.demanda for k, (d, c) in
                           enumerate(zip(r.plan.demanda[rol], r.plan.cobertura[rol])) if d > c]
                filas_h.append({"Día": f"{r.dia:%d/%m} {'LMXJVSD'[r.dia.weekday()]}", "Vuelos": r.vuelos,
                                "Personas": r.personas, "Horas sin cubrir": round(r.sin_cubrir, 1),
                                "Antes de tus cambios": round(dif[r.dia][0].sin_cubrir, 1),
                                "Dónde falta": ", ".join(f"{rol} {h:.1f} h" for rol, h in faltan.items()),
                                "Entre": "" if not franjas else
                                f"{INICIO_MAS_TEMPRANO // 60 + min(franjas) // 4:02d}:{min(franjas) % 4 * 15:02d}"
                                f" y {(INICIO_MAS_TEMPRANO // 60 + (max(franjas) + 1) // 4) % 24:02d}:"
                                f"{(max(franjas) + 1) % 4 * 15:02d}"})
            st.dataframe(filas_h, hide_index=True, width="stretch")
            st.caption("«Dónde falta» cuenta cada puesto por separado; «Horas sin cubrir» ya descuenta lo que "
                       "puede tapar quien sobra de otro puesto.")
    else:
        st.info("Sin los vuelos de este mes no se pueden comprobar los huecos: súbelos en la pestaña Datos.")
    c1, c2 = st.columns(2)
    if c1.button("Guardar cambios", type="primary", disabled=not cambiado, key=f"g_{clave}"):
        arch.guardar_cuadrante(anio, mes, nuevas, tipo)
        st.session_state.pop(clave, None)
        st.toast("Cambios guardados.")
        st.rerun()
    if cambiado:
        c1.caption("Tienes cambios sin guardar.")
    with tempfile.TemporaryDirectory() as tmp:
        salida = exportar_cuadrante(nuevas, anio, mes, Path(tmp) / f"cuadrante_{tipo}_{anio}-{mes:02d}.xlsx", colores)
        c2.download_button("Descargar en Excel", salida.read_bytes(), salida.name, key=f"d_{clave}",
                           help="Con el mismo formato que se sube: se puede volver a subir.")


datos_tab, mensual_tab, diaria_tab, resumen_tab, ausencias_tab, anual_tab, vacaciones_tab, empresa_tab = st.tabs(
    ["Datos", "Cuadrante del mes", "Parrilla del día", "Resumen", "Plantilla y ausencias", "Rotaciones del año",
     "Vacaciones del año", "Empresa y reglas"])

with empresa_tab:
    pagina_empresa.mostrar(perfil, perfiles, EJEMPLOS, PROPIAS)

with datos_tab:
    st.subheader("Los datos de cada mes, subidos una vez")
    st.write("Sube aquí el cuadrante real y los vuelos de cada mes. Al leerlos, cada nombre se cambia por un "
             "código (P0001, P0002…; quien ya trae código de empleado lo conserva) y solo se guardan los códigos, "
             "en este ordenador. El resto de pestañas usa lo que hay aquí.")
    guardados = arch.meses()
    if guardados:
        st.dataframe([{"Mes": nombre_mes(a, m), **{TIPOS[t]: "✓" if t in hay else "" for t in TIPOS},
                       "Vuelos": "✓" if "vuelos" in hay else ""} for a, m, hay in guardados],
                     hide_index=True, width="content")
    else:
        st.info("Aún no hay nada guardado. Empieza por el cuadrante real del último mes y los vuelos del mes que "
                "quieras planificar.")
    contratos_g, formacion_g = arch.contratos(), arch.formacion()
    st.caption(f"Contratos: {len(contratos_g)} personas." if contratos_g else "Contratos: sin subir.")
    st.caption(f"Formación: {len(formacion_g)} personas." if formacion_g else "Formación: sin subir.")

    with st.expander("Subir archivos", expanded=not guardados):
        hoy_d = date.today()
        anio_d, mes_d = elegir_mes("Mes", hoy_d.replace(day=1), "dat")
        real_d = st.file_uploader("Cuadrante real de ese mes (el publicado o el que se trabajó)", type=["xlsx"],
                                  key="real_d")
        vuelos_d = st.file_uploader("Vuelos de ese mes (Flights, PACOTRON u OMS)", type=["xlsx", "xls", "csv"],
                                    key="vuelos_d")
        contratos_d = st.file_uploader("Contratos de la plantilla (Empleado, Contrato). Sirve para todos los meses",
                                       type=["xlsx", "csv"], key="contratos_d")
        formacion_d = st.file_uploader("Formación de cada persona: el Excel EVE-FD o el PARRITRON (hoja AJUSTES, "
                                       "capacitaciones PCP, cinta, carreteo, PBT, TBL, JAR). Nadie va a la cinta, al "
                                       "carreteo o al pushback sin ella", type=["xlsx", "xlsm"], key="formacion_d")
        if st.button("Guardar", type="primary", disabled=not (real_d or vuelos_d or contratos_d or formacion_d)):
            hecho = []
            try:
                with st.spinner("Leyendo y cambiando nombres por códigos…"):
                    if real_d:
                        filas_d = cuadrante_subido(real_d, anio_d)
                        arch.guardar_cuadrante(anio_d, mes_d, filas_d, "real")
                        if (anio_d, mes_d) == max(meses_con("real")):
                            almacen.guardar_plantilla(filas_d)
                        hecho.append(f"cuadrante real de {nombre_mes(anio_d, mes_d)} ({len(filas_d)} personas)")
                    if vuelos_d:
                        v_d = vuelos_subidos(vuelos_d, anio_d, mes_d)
                        arch.guardar_vuelos(anio_d, mes_d, v_d)
                        hecho.append(f"{sum(map(len, v_d.values()))} vuelos de {nombre_mes(anio_d, mes_d)}")
                    if contratos_d:
                        c_d = codigos.claves(leer_subido(contratos_d, leer_contratos))
                        arch.guardar_contratos(c_d)
                        hecho.append(f"contratos de {len(c_d)} personas")
                    if formacion_d:
                        f_d = codigos.fichas(leer_subido(formacion_d, leer_habilitaciones, conf))
                        arch.guardar_formacion(f_d)
                        hecho.append(f"formación de {len(f_d)} personas")
                st.session_state["guardado_d"] = "Guardado: " + ", ".join(hecho) + "."
                st.rerun()
            except Exception as error:
                st.error(f"No se ha podido leer: {error}")
    if (aviso_d := st.session_state.pop("guardado_d", None)):
        st.success(aviso_d)

    if guardados:
        st.markdown("#### Ver y corregir")
        c1, c2 = st.columns(2)
        mes_v = c1.selectbox("Mes", [(a, m) for a, m, _ in guardados], format_func=lambda x: nombre_mes(*x),
                             key=f"mes_v_{demo}")
        hay_v = next(h for a, m, h in guardados if (a, m) == mes_v)
        que = c2.radio("Qué", [t for t in ("real", "programa", "vuelos") if t in hay_v], horizontal=True,
                       format_func=lambda t: TIPOS.get(t, "Vuelos"), key=f"que_v_{demo}")
        if que == "vuelos":
            vuelos_v = arch.vuelos(*mes_v)
            dias_v = [d for d in sorted(vuelos_v)]
            dia_v = st.select_slider("Día", dias_v, format_func=lambda d: f"{d:%d/%m}", key=f"dia_v_{demo}")
            base_v = tabla_vuelos(vuelos_v[dia_v])
            clave_v = f"vuelos_{demo}_{dia_v}"
            editados_v = st.data_editor(base_v, key=clave_v, hide_index=True, num_rows="dynamic",
                                        width="stretch")
            st.caption(f"{len(base_v)} filas. Horas en HH:MM; «+1» si es del día siguiente. Puesto: C… contacto, "
                       "R… remoto.")
            if st.button("Guardar los vuelos de este día", type="primary", disabled=editados_v == base_v):
                try:
                    vuelos_v[dia_v] = desde_tabla_vuelos(editados_v, dia_v)
                    arch.guardar_vuelos(*mes_v, vuelos_v)
                    st.session_state.pop(clave_v, None)
                    st.toast("Vuelos guardados.")
                    st.rerun()
                except ValueError as error:
                    st.error(f"Hay una hora que no se entiende: {error}")
        else:
            st.caption("Cada celda: 06:00-14:00 (o 6-14), un partido 06:00-10:00 / 15:00-19:00, vacía si libra, o "
                       "el motivo de la ausencia (" + ", ".join(colores) + ").")
            editor_cuadrante(*mes_v, que)

with vacaciones_tab:
    st.subheader("Reparto de las vacaciones del año por puntos")
    st.write("Sube las solicitudes: Empleado, Función, Puntos acumulados, Antigüedad y las quincenas que pide "
             "cada uno por orden de preferencia (JUL-1, AGO-2…). Elige primero quien menos puntos lleva; cada "
             "quincena suma los puntos de su temporada para el año siguiente, y en cada quincena solo puede "
             "estar de vacaciones un cupo de cada función. Los nombres se cambian por su código.")
    anio_v = st.number_input("Año de las vacaciones", 2020, 2100, 2027 if demo else date.today().year + 1,
                             key="anio_v_demo" if demo else "anio_v")
    solicitudes_v = archivo("Solicitudes de vacaciones", ["xlsx", "csv"], "sv", "solicitudes_vacaciones_2027.xlsx")
    temporadas = conf.datos.get("vacaciones", {}).get("temporadas", [])
    if temporadas:
        st.caption("Temporadas (de la configuración): " + "; ".join(
            f"{t['nombre']} ({', '.join(t['periodos'])}): {t['puntos']} puntos" for t in temporadas)
                   + f"; resto: {conf.datos['vacaciones'].get('puntos_por_defecto', 1)} puntos.")
    if st.button("Repartir vacaciones", type="primary", disabled=not solicitudes_v):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                sol = codigos.lista(vacaciones.leer_solicitudes(guardar(solicitudes_v, Path(tmp))))
                usado = vacaciones.repartir(sol, int(anio_v), conf)
                periodos = vacaciones.quincenas(int(anio_v))
                salida = Path(tmp) / f"vacaciones_{int(anio_v)}.xlsx"
                exportar_vacaciones(sol, int(anio_v), usado, vacaciones.cupos(sol, periodos, conf),
                                    vacaciones.valor_periodos(periodos, conf), salida)
                st.session_state["vacaciones"] = (int(anio_v), sol, salida.read_bytes())
            except Exception as error:
                st.error(f"No se ha podido repartir: {error}")
    if st.session_state.get("vacaciones"):
        anio_hecho, sol, excel = st.session_state["vacaciones"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Personas", len(sol))
        c2.metric("Con todo lo que pidieron", sum(1 for x in sol if x.asignados and x.conseguidas == len(x.asignados)))
        c3.metric("Con parte", sum(1 for x in sol if 0 < x.conseguidas < len(x.asignados)))
        c4.metric("Con nada de lo pedido", sum(1 for x in sol if x.conseguidas == 0))
        st.download_button("Descargar reparto", excel, f"vacaciones_{anio_hecho}.xlsx", type="primary")
        st.dataframe([{"Código": x.empleado, "Función": x.funcion, "Puntos": x.puntos,
                       "Pidió": ", ".join(x.preferencias), "Le tocan": ", ".join(x.asignados)} for x in sol],
                     hide_index=True, width="stretch")
        if st.button("Apuntar estas vacaciones en Plantilla y ausencias"):
            apuntadas = repetidas = 0
            for empleado, funcion, desde, hasta in vacaciones.como_ausencias(sol, anio_hecho):
                try:
                    almacen.anadir(empleado, funcion, "Vacaciones", desde, hasta, f"Reparto {anio_hecho}")
                    apuntadas += 1
                except ValueError:
                    repetidas += 1
            st.success(f"Apuntadas {apuntadas} quincenas de vacaciones."
                       + (f" {repetidas} no, porque ya había algo apuntado esos días." if repetidas else ""))

with resumen_tab:
    st.subheader("¿Cubre el cuadrante los vuelos?")
    st.write("Franja a franja de 15 minutos, cuánta gente hay en el cuadrante y cuánta piden los vuelos. Usa los "
             "cuadrantes y vuelos guardados en la pestaña Datos.")
    meses_s = meses_con("vuelos")
    meses_s = [x for x in meses_s if any(arch.cuadrante(*x, t) for t in TIPOS)]
    if not meses_s:
        st.info("Hace falta un mes con vuelos y algún cuadrante guardados (pestaña Datos).")
    else:
        c1, c2, c3 = st.columns(3)
        mes_s = c1.selectbox("Mes", meses_s, format_func=lambda x: nombre_mes(*x), key=f"mes_s_{demo}")
        tipos_s = [t for t in TIPOS if arch.cuadrante(*mes_s, t)]
        tipo_s = c2.selectbox("Cuadrante", tipos_s, format_func=TIPOS.get, key=f"tipo_s_{demo}")
        otro_tipo = c3.selectbox("Comparar con", [None] + [t for t in tipos_s if t != tipo_s],
                                 format_func=lambda t: "(nada)" if t is None else TIPOS[t], key=f"otro_s_{demo}")
        dias_s = dias_del_mes(*mes_s)
        vuelos_s = arch.vuelos(*mes_s)
        resumen = resumir(arch.cuadrante(*mes_s, tipo_s), vuelos_s, conf, dias_s)
        comparado = resumir(arch.cuadrante(*mes_s, otro_tipo), vuelos_s, conf, dias_s) if otro_tipo else None

        def cifras(res):
            pedidas = sum(sum(dp.plan.demanda[r]) for dp in res for r in dp.plan.demanda) * 15 / 60
            sin = sum(r.sin_cubrir for r in res)
            return sum(r.horas for r in res), sin, 100 * (1 - sin / pedidas) if pedidas else 0.0

        horas_s, sin_cubrir, cubierto = cifras(resumen)
        diferencia = None
        if comparado:
            h2, s2, c2_ = cifras(comparado)
            diferencia = (horas_s - h2, sin_cubrir - s2, cubierto - c2_)
            st.caption(f"{TIPOS[otro_tipo]}: {numero(h2)} horas, {numero(s2)} sin cubrir, {c2_:.1f} % cubierto. "
                       "Las flechas son la diferencia.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vuelos en el mes", numero(sum(r.vuelos for r in resumen)))
        c2.metric("Horas planificadas", numero(horas_s),
                  None if diferencia is None else f"{numero(diferencia[0])} h", delta_color="inverse")
        c3.metric("Necesidad cubierta", f"{cubierto:.1f} %",
                  None if diferencia is None else f"{diferencia[2]:+.1f} puntos")
        c4.metric("Horas sin cubrir", numero(sin_cubrir),
                  None if diferencia is None else f"{numero(diferencia[1])} h", delta_color="inverse")
        st.caption("Las horas sin cubrir ya cuentan que quien sobra puede cubrir otro puesto (en Azul, un TL o PB "
                   f"hace de operario): pasa {sum(r.tl_pb_como_operario for r in resumen):,.0f} horas en el mes.".replace(",", "."))

        c1, c2 = st.columns([2, 1])
        dia_s = c1.select_slider("Día", [r.dia for r in resumen], format_func=lambda d: f"{d:%d/%m}", key="dia_s")
        pasaje_s = pasaje.categorias(conf)
        plataforma_s = [r for r in resumen[0].plan.demanda if r not in pasaje_s]
        roles_s = sorted(plataforma_s, key=lambda r: r != "Operario") + [
            r for r in pasaje_s if any(any(x.plan.demanda.get(r, [])) for x in resumen)]
        rol = c2.radio("Puesto", roles_s, horizontal=True, key="rol_s")
        plan = next(r for r in resumen if r.dia == dia_s).plan
        # Las franjas empiezan a las 04:00 y pueden pasar de medianoche: el eje va en horas desde las 00:00
        # de ese día (25 = la 01:00 del día siguiente).
        pares = list(zip(plan.demanda[rol], plan.cobertura[rol]))
        ultima = max((k for k, (d, c) in enumerate(pares) if d or c), default=0) + 2
        filas_g = []
        for k, (d, c) in enumerate(pares[:ultima]):
            minuto = INICIO_MAS_TEMPRANO + k * 15
            hora, etiqueta = minuto / 60, f"{minuto // 60 % 24:02d}:{minuto % 60:02d}"
            filas_g += [{"Hora": hora, "Franja": etiqueta, "Personas": c, "Serie": "En el cuadrante"},
                        {"Hora": hora, "Franja": etiqueta, "Personas": d, "Serie": "Piden los vuelos"}]
        escala = alt.Scale(domain=["En el cuadrante", "Piden los vuelos"], range=[CIAN, NARANJA])
        fin_eje = INICIO_MAS_TEMPRANO / 60 + ultima / 4
        base = alt.Chart(alt.Data(values=filas_g)).encode(
            x=alt.X("Hora:Q", title=None, scale=alt.Scale(domain=[INICIO_MAS_TEMPRANO / 60, fin_eje], nice=False),
                    axis=alt.Axis(values=list(range(INICIO_MAS_TEMPRANO // 60, int(fin_eje) + 1, 2)),
                                  labelExpr="(datum.value % 24 < 10 ? '0' : '') + (datum.value % 24) + ':00'")),
            y=alt.Y("Personas:Q"), color=alt.Color("Serie:N", scale=escala, legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("Franja:N", title="Hora"), "Serie:N", "Personas:Q"])
        grafico = (base.transform_filter(alt.datum.Serie == "En el cuadrante").mark_area(opacity=0.35, interpolate="step-after")
                   + base.transform_filter(alt.datum.Serie == "Piden los vuelos").mark_line(strokeWidth=2, interpolate="step-after"))
        st.altair_chart(grafico.properties(height=320), width="stretch")
        with st.expander("Día a día"):
            st.dataframe([{"Día": r.dia.strftime("%d/%m"), "Vuelos": r.vuelos, "Personas": r.personas,
                           "Horas": r.horas, "Horas sin cubrir": round(r.sin_cubrir, 1),
                           "TL/PB de operario (h)": round(r.tl_pb_como_operario, 1)} for r in resumen],
                         hide_index=True)

with anual_tab:
    st.subheader("Calendario de rotaciones de un año")
    st.write("A partir del último cuadrante real guardado (y del mes anterior, si también está), el programa sigue "
             "el ciclo de cada persona desde donde va, sin reiniciarlo en enero, y marca cada día de mañana, de "
             "tarde o libre.")
    reales_a = meses_con("real")
    if not reales_a:
        st.info("Sube antes un cuadrante real en la pestaña Datos.")
    else:
        ultimo_a = st.selectbox("Último cuadrante", reales_a, format_func=lambda x: nombre_mes(*x), key=f"ult_a_{demo}")
        anio_obj = st.number_input("Año a calcular", 2020, 2100, 2027 if demo else date.today().year + 1, key="anio_obj")
        anterior_a = (ultimo_a[0], ultimo_a[1] - 1) if ultimo_a[1] > 1 else (ultimo_a[0] - 1, 12)
        if anterior_a in reales_a:
            st.caption(f"También se usa el de {nombre_mes(*anterior_a)}, que da más seguridad.")
        if st.button("Calcular rotaciones", type="primary"):
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    meses_a = [(arch.cuadrante(*x), dias_del_mes(*x)) for x in (anterior_a, ultimo_a) if x in reales_a]
                    rot = rotaciones_recientes(meses_a)
                    salida = Path(tmp) / f"rotaciones_{int(anio_obj)}.xlsx"
                    exportar_anio(rot, int(anio_obj), salida)
                    fijas = [r for r in rot if r.patron != "irregular"]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Personas", len(rot))
                    c2.metric("Con rotación fija", len(fijas))
                    c3.metric("Sin rotación fija", len(rot) - len(fijas))
                    st.download_button("Descargar rotaciones", salida.read_bytes(), salida.name, type="primary")
                except Exception as error:
                    st.error(f"No se ha podido calcular: {error}")

with ausencias_tab:
    st.subheader("Bajas, vacaciones, sanciones y permisos")
    st.write("Lo que apuntes aquí lo tienen en cuenta solos el cuadrante del mes y la parrilla del día. "
             "Se guarda en este ordenador, solo con códigos.")

    plantilla = almacen.plantilla()
    with st.expander(f"Plantilla: {len(plantilla)} personas" if plantilla else "Plantilla: aún no cargada",
                     expanded=not plantilla):
        st.write("La plantilla sale del cuadrante real más reciente guardado en la pestaña Datos, y se actualiza "
                 "sola cada vez que subes uno más nuevo.")
        if meses_con("real") and st.button("Actualizar con el cuadrante real de "
                                           f"{nombre_mes(*max(meses_con('real')))}"):
            n = almacen.guardar_plantilla(arch.cuadrante(*max(meses_con("real"))))
            st.success(f"Plantilla guardada: {n} personas.")
            st.rerun()
        if plantilla:
            st.dataframe([{"Código": e, "Función": f} for e, f in plantilla], hide_index=True, height=240)

    st.markdown("#### Apuntar una ausencia")
    if not plantilla:
        st.info("Primero sube un cuadrante real en la pestaña Datos.")
    else:
        with st.form("nueva", clear_on_submit=True):
            persona = st.selectbox("Persona", plantilla, format_func=lambda p: f"{p[0]} ({p[1]})", index=None,
                                   placeholder="Escribe el código para buscar")
            motivo = st.selectbox("Motivo", list(colores))
            c1, c2, c3 = st.columns(3)
            desde = c1.date_input("Desde", value=date.today(), format="DD/MM/YYYY")
            abierta = c3.checkbox("Sin fecha de fin (hasta que le den el alta)", value=True)
            hasta = c2.date_input("Hasta (incluido)", value=date.today(), format="DD/MM/YYYY")
            nota = st.text_input("Nota (opcional, sin nombres)")
            if st.form_submit_button("Apuntar", type="primary"):
                if persona is None:
                    st.error("Elige una persona.")
                else:
                    try:
                        almacen.anadir(persona[0], persona[1], motivo, desde, None if abierta else hasta, nota)
                        st.success(f"Apuntado: {persona[0]}, {motivo.lower()}.")
                    except ValueError as error:
                        st.error(str(error))

    registros = almacen.registros()
    hoy = date.today()
    fuera_hoy = [r for r in registros if r.activa(hoy)]
    abiertas = [r for r in registros if r.abierta]
    st.markdown(f"#### Pendientes de alta: {len(abiertas)}")
    st.caption(f"Hoy hay {len(fuera_hoy)} personas fuera. Para las que tienen fecha de fin no hace falta dar el alta.")
    for r in sorted(abiertas, key=lambda r: r.desde):
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.write(f"**{r.empleado}** ({r.funcion}): {r.motivo.lower()} desde el {r.desde:%d/%m/%Y}"
                 + (f". {r.nota}" if r.nota else ""))
        alta = c2.date_input("Día que vuelve", value=hoy, format="DD/MM/YYYY", key=f"alta_{r.id}",
                             label_visibility="collapsed")
        if c3.button("Dar alta", key=f"btn_{r.id}"):
            try:
                almacen.dar_alta(r.id, alta)
                st.rerun()
            except ValueError as error:
                st.error(str(error))

    with st.expander(f"Todas las ausencias apuntadas ({len(registros)})"):
        if registros:
            st.dataframe([{"Código": r.empleado, "Función": r.funcion, "Motivo": r.motivo,
                           "Desde": r.desde.strftime("%d/%m/%Y"),
                           "Hasta": r.hasta.strftime("%d/%m/%Y") if r.hasta else "abierta", "Nota": r.nota}
                          for r in sorted(registros, key=lambda r: r.desde, reverse=True)], hide_index=True)
            a_borrar = st.selectbox("Borrar una apuntada por error", registros, index=None,
                                    format_func=lambda r: f"{r.empleado}, {r.motivo.lower()}, {r.desde:%d/%m/%Y}")
            if st.button("Borrar", disabled=a_borrar is None):
                almacen.borrar(a_borrar.id)
                st.rerun()

    st.markdown("#### Reorganizar el cuadrante para cubrir a quien falta")
    st.write("Con el cuadrante y los vuelos guardados del mes, el programa cambia el horario a las menos personas "
             "posibles para cubrir los huecos, y te da la lista de cambios para avisarles.")
    meses_r = meses_con("vuelos")
    meses_r = [x for x in meses_r if any(arch.cuadrante(*x, t) for t in TIPOS)]
    if not meses_r:
        st.info("Hace falta un mes con vuelos y algún cuadrante guardados (pestaña Datos).")
    else:
        c1, c2 = st.columns(2)
        mes_r = c1.selectbox("Mes", meses_r, format_func=lambda x: nombre_mes(*x), key=f"mes_r_{demo}")
        tipo_r = c2.radio("Cuadrante publicado", [t for t in ("programa", "real") if arch.cuadrante(*mes_r, t)],
                          format_func=TIPOS.get, horizontal=True, key=f"tipo_r_{demo}")
        dias_r = dias_del_mes(*mes_r)
        rango = st.date_input("Días a reorganizar", value=(max(hoy, dias_r[0]) if hoy <= dias_r[-1] else dias_r[0],
                                                             min(dias_r[-1], date.fromordinal(max(hoy, dias_r[0]).toordinal() + 6))),
                              min_value=dias_r[0], max_value=dias_r[-1], format="DD/MM/YYYY", key=f"rango_{mes_r}")
        aviso_r = st.date_input("Día en que se avisa de los cambios", value=NOVIEMBRE_DEMO if demo else hoy,
                                format="DD/MM/YYYY", key="aviso_r_demo" if demo else "aviso_r",
                                help="Las reglas de preaviso de cada contrato están en la configuración (en Azul: "
                                     "parciales 3 días, tiempo completo 5 días; con menos, solo perentorias).")
        if not arch.contratos():
            st.caption("Sin contratos guardados no se sabe a quién se puede mover con qué preaviso (pestaña Datos).")
        if st.button("Reorganizar", type="primary", disabled=len(rango) != 2):
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                try:
                    with st.status("Reorganizando día a día…") as estado:
                        filas = arch.cuadrante(*mes_r, tipo_r)
                        guardados_r = arch.vuelos(*mes_r)
                        vuelos = {d: v for d in dias_r if rango[0] <= d <= rango[1]
                                  if (v := emparejar_giros(guardados_r.get(d, [])))}
                        barra = st.progress(0.0)
                        cm, cambios = reorganizar(filas, dias_r, vuelos, almacen.ausencias(), conf, 20,
                                                  progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"),
                                                  contratos=arch.contratos(), aviso=aviso_r)
                        salida = tmp / f"cuadrante_reorganizado_{mes_r[0]}-{mes_r[1]:02d}.xlsx"
                        exportar_mes(cm, salida, False, colores, cambios)
                        estado.update(label="Reorganización lista", state="complete")
                    st.download_button("Descargar cuadrante reorganizado", salida.read_bytes(), salida.name, type="primary")
                    if cambios:
                        st.dataframe([{"Día": c.dia.strftime("%d/%m"), "Código": c.empleado, "Función": c.funcion,
                                       "Contrato": c.contrato, "Antes": c.antes, "Ahora": c.despues, "Cambio": c.tipo,
                                       "Preaviso (días)": c.preaviso, "Horas nuevas": c.horas or "",
                                       "Tipo de horas": c.tipo_horas}
                                      for c in sorted(cambios, key=lambda c: (c.dia, c.tipo))], hide_index=True)
                    else:
                        st.info("No hace falta cambiar nada en esos días.")
                except Exception as error:
                    st.error(f"No se ha podido reorganizar: {error}")

with mensual_tab:
    st.subheader("Cuadrante del mes a partir de los vuelos")
    st.write("El programa continúa la rotación de cada persona desde el cuadrante real de un mes anterior y le "
             "pone el horario que mejor cubre los vuelos de cada día. Después lo puedes corregir aquí mismo.")
    hoy = date.today()
    siguiente = date(hoy.year + hoy.month // 12, hoy.month % 12 + 1, 1)
    anio, mes = elegir_mes("A planificar", siguiente, "plan", NOVIEMBRE_DEMO)
    vuelos_m = arch.vuelos(anio, mes)
    reales_m = sorted((x for x in meses_con("real") if x < (anio, mes)), reverse=True)
    if not vuelos_m:
        st.warning(f"Faltan los vuelos de {nombre_mes(anio, mes)}: súbelos en la pestaña Datos.")
    if not reales_m:
        st.warning("Falta un cuadrante real de un mes anterior: súbelo en la pestaña Datos.")
    referencia_m = st.selectbox("Cuadrante de referencia (normalmente el real del mes anterior)", reales_m,
                                format_func=lambda x: f"Real de {nombre_mes(*x)}", key=f"ref_m_{demo}_{anio}_{mes}")
    contratos_m = arch.contratos()
    st.caption((f"Contratos guardados de {len(contratos_m)} personas: a los parciales se les ajustan las horas a los "
                "vuelos y a los TC se les dan sus 8 horas." if contratos_m else
                "Sin contratos guardados (pestaña Datos), todos se planifican con la jornada del mes de referencia.")
               + " Las ausencias apuntadas en Plantilla y ausencias se tienen en cuenta solas.")
    ausencias_archivo = st.file_uploader("Más ausencias de este mes (opcional): Empleado, Desde, Hasta, Motivo",
                                         type=["xlsx", "csv"], key="aus")
    segundos = st.slider("Tiempo de cálculo por día (segundos)", 10, 60, 30, key="seg",
                         help="Con menos de 30 segundos el resultado deja más huecos.")
    hay_programa = arch.cuadrante(anio, mes, "programa") is not None
    if hay_programa:
        st.caption("Ya hay un cuadrante del programa guardado para este mes: si lo generas otra vez, se sustituye "
                   "(con tus correcciones).")
    if st.button("Generar cuadrante", type="primary", disabled=not (vuelos_m and referencia_m)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                with st.status("Aprendiendo del cuadrante de referencia…") as estado:
                    dias_ref = dias_del_mes(*referencia_m)
                    perfiles_m = aprender_perfiles(arch.cuadrante(*referencia_m), dias_ref, conf, contratos_m)
                    ausencias = almacen.ausencias()
                    if ausencias_archivo:
                        ausencias += codigos.lista(leer_ausencias(guardar(ausencias_archivo, tmp)))
                    estado.update(label=f"{len(perfiles_m)} personas y {sum(map(len, vuelos_m.values()))} vuelos. "
                                        "Planificando día a día…")
                    barra = st.progress(0.0)
                    cm = planificar_mes(vuelos_m, perfiles_m, dias_ref[0], conf, segundos, ausencias,
                                        progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"))
                    arch.guardar_cuadrante(anio, mes, filas_desde_plan(cm, colores), "programa")
                    st.session_state.pop(f"editor_{demo}_programa_{anio}_{mes}", None)
                    salida = tmp / f"cuadrante_{anio}-{mes:02d}_con_cobertura.xlsx"
                    exportar_mes(cm, salida, False, colores)
                    st.session_state["excel_mes"] = (anio, mes, salida.name, salida.read_bytes())
                    estado.update(label="Cuadrante listo y guardado", state="complete")
                st.rerun()
            except Exception as error:  # se enseña al usuario en lugar de una traza
                st.error(f"No se ha podido generar: {error}")
    if arch.cuadrante(anio, mes, "programa") is not None:
        st.markdown(f"#### Cuadrante del programa de {nombre_mes(anio, mes)}")
        st.caption("Corrige lo que haga falta: 06:00-14:00 (o 6-14), un partido 06:00-10:00 / 15:00-19:00, vacía "
                   "si libra, o el motivo de la ausencia (" + ", ".join(colores) + "). Al cambiar una celda se "
                   "recalculan los huecos; pulsa Guardar cambios para quedártelos.")
        editor_cuadrante(anio, mes, "programa")
        if (excel := st.session_state.get("excel_mes")) and excel[:2] == (anio, mes):
            st.download_button("Descargar tal como salió del programa, con las hojas de cobertura y horas",
                               excel[3], excel[2])

with diaria_tab:
    st.subheader("Parrilla del día a partir del cuadrante")
    st.write("Con el cuadrante y los vuelos guardados, el programa forma los equipos con quien coincide en "
             "horario y les asigna los vuelos. Después puedes cambiar quién va en cada equipo y qué vuelo lleva.")
    dia = st.date_input("Día", value=date(2026, 11, 6) if demo else date.today(), format="DD/MM/YYYY",
                        key="dia_demo" if demo else "dia")
    tipos_d = [t for t in ("programa", "real") if arch.cuadrante(dia.year, dia.month, t) is not None]
    vuelos_mes_d = arch.vuelos(dia.year, dia.month) or {}
    if not tipos_d:
        st.warning(f"No hay ningún cuadrante guardado de {nombre_mes(dia.year, dia.month)} (pestañas Datos o "
                   "Cuadrante del mes).")
    fuente_d = st.radio("Cuadrante", tipos_d, format_func=TIPOS.get, horizontal=True, key=f"fuente_d_{demo}")
    with st.expander("Usar otro archivo de vuelos para este día (por ejemplo, el libro de parrillas)"):
        vuelos_dia = st.file_uploader("Vuelos (Flights, PACOTRON, OMS o libro de parrillas)",
                                      type=["xlsx", "xls", "csv"], key="vd")
        hoja = st.text_input("Si es un libro de parrillas, nombre de la hoja del día (por ejemplo 15-10)", key="hj")
    if not vuelos_dia:
        st.caption(f"{len(vuelos_mes_d.get(dia, []))} vuelos guardados para este día." if vuelos_mes_d else
                   "No hay vuelos guardados de este mes: súbelos en Datos o aquí arriba.")
    fichas_d = arch.formacion()
    if not fichas_d:
        st.caption("Sin formación guardada, cada persona tiene las habilitaciones de su función.")

    if st.button("Generar parrilla", type="primary",
                 disabled=not (fuente_d and (vuelos_dia or vuelos_mes_d.get(dia)))):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                with st.spinner("Formando equipos y asignando vuelos…"):
                    if vuelos_dia and hoja:
                        vuelos, incidencias = leer_vuelos_parrilla(guardar(vuelos_dia, tmp), hoja, dia)[0], []
                    elif vuelos_dia:
                        vuelos, incidencias = leer_vuelos(guardar(vuelos_dia, tmp), dia, conf.zona_horaria)
                        vuelos = emparejar_giros(vuelos)
                    else:
                        vuelos, incidencias = emparejar_giros(vuelos_mes_d[dia]), []
                    filas_dia = arch.cuadrante(dia.year, dia.month, fuente_d)
                    p = generar_parrilla_cuadrante(dia, vuelos, filas_dia, conf, incidencias, 20, almacen.ausencias(),
                                                   fichas_d)
                    revisadas = validar_grupos(p.grupos, p.asignadas, dia)
                    previas = [i for i in p.incidencias if i not in revisadas]
                    tareas_p = pasaje.tareas_pasaje(vuelos, conf)
                    responsables = {}
                    if tareas_p:
                        fuera = {a.empleado for a in almacen.ausencias() if a.desde <= dia <= a.hasta}
                        for categoria in dict.fromkeys(t.categoria for t in tareas_p):
                            pasaje.asignar([t for t in tareas_p if t.categoria == categoria],
                                           pasaje.agentes_del_dia(filas_dia, dia, conf, categoria, fuera))
                        responsables = pasaje.agentes_del_dia(filas_dia, dia, conf, pasaje.RESPONSABLE, fuera)
                    vez = st.session_state.get("parrilla", {}).get("vez", 0) + 1
                    st.session_state["parrilla"] = {"dia": dia, "p": p, "previas": previas, "tareas_p": tareas_p,
                                                    "responsables": responsables, "vez": vez, "demo": demo}
            except Exception as error:
                st.error(f"No se ha podido generar: {error}")

    hecha = st.session_state.get("parrilla")
    if hecha and hecha["dia"] == dia and hecha["demo"] == demo:
        p = copy.deepcopy(hecha["p"])
        vez = hecha["vez"]
        personas = {}
        for g in p.grupos:
            for e in g.equipos:
                personas.update({m.id: m for m in e.miembros.values() if m})
        for lista in (p.reparto.hipodromo, p.reparto.mandos):
            for e in lista:
                personas.update({m.id: m for m in e.miembros.values() if m})
        personas.update({m.id: m for m in p.reparto.reserva})
        opciones = ["—"] + sorted(personas)
        st.markdown("#### Equipos y vuelos")
        st.caption("Cambia a una persona de equipo eligiendo su código, o un vuelo de equipo. Los avisos se "
                   "recalculan al momento. Libres: " + (", ".join(dict.fromkeys(m.id for m in p.reparto.reserva)) or "nadie") + ".")
        for n, g in enumerate(p.grupos):
            if not g.equipos and not g.tareas:
                continue
            etiquetas = g.recurso.etiquetas()
            st.markdown(f"##### {g.recurso.nombre}")
            c1, c2 = st.columns([3, 2])
            base_e = [{"Equipo": e.codigo, "Horario": f"{hhmm_(e.inicio)}-{hhmm_(e.fin)}",
                       **{et: (e.miembros.get(et).id if e.miembros.get(et) else "—") for et in etiquetas}}
                      for e in g.equipos]
            editados_e = c1.data_editor(
                base_e, key=f"eq_{vez}_{n}", hide_index=True, disabled=["Equipo", "Horario"], width="stretch",
                column_config={et: st.column_config.SelectboxColumn(et, options=opciones) for et in etiquetas})
            for e, fila in zip(g.equipos, editados_e):
                for et in etiquetas:
                    e.miembros[et] = personas.get(fila.get(et) or "—")
            codigos_e = ["—"] + [e.codigo for e in g.equipos]
            base_t = [{"Vuelo": t.vuelo.codigo, "Trabajo": t.tipo.replace("_", " ").lower(),
                       "Desde": hhmm_(t.inicio), "Hasta": hhmm_(t.fin), "Equipo": p.asignadas.get(t.id, "—")}
                      for t in sorted(g.tareas, key=lambda t: t.inicio)]
            orden = sorted(g.tareas, key=lambda t: t.inicio)
            editados_t = c2.data_editor(
                base_t, key=f"tr_{vez}_{n}", hide_index=True, disabled=["Vuelo", "Trabajo", "Desde", "Hasta"],
                width="stretch",
                column_config={"Equipo": st.column_config.SelectboxColumn("Equipo", options=codigos_e)})
            for t, fila in zip(orden, editados_t):
                if fila.get("Equipo") not in (None, "", "—"):
                    p.asignadas[t.id] = fila["Equipo"]
                else:
                    p.asignadas.pop(t.id, None)
        p.incidencias = hecha["previas"] + validar_grupos(p.grupos, p.asignadas, dia)
        grupos = [e for e in p.reparto.equipos if e.seccion == "GRUPOS"]
        tareas_p = hecha["tareas_p"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vuelos", len(p.vuelos))
        c2.metric("Equipos", len(grupos))
        c3.metric("De refuerzo", len(p.reparto.equipos) - len(grupos))
        c4.metric("Trabajos sin equipo", sum(1 for g in p.grupos for t in g.tareas if t.id not in p.asignadas))
        pendientes = [i for i in p.incidencias if i.gravedad == "PENDIENTE"]
        if pendientes:
            st.warning(f"{len(pendientes)} cosas por resolver:\n" + "\n".join(f"- {i.detalle}" for i in pendientes[:15])
                       + (f"\n- y {len(pendientes) - 15} más (hoja Incidencias del Excel)." if len(pendientes) > 15 else ""))
        else:
            st.success("Nada pendiente: todos los vuelos tienen equipo y no hay nadie en dos sitios a la vez.")
        with st.expander(f"Todos los avisos ({len(p.incidencias)})"):
            st.dataframe([{"Gravedad": i.gravedad, "Qué": i.codigo, "Detalle": i.detalle} for i in p.incidencias],
                         hide_index=True, width="stretch")
        if tareas_p:
            st.markdown("#### Pasaje")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Facturaciones", sum(1 for t in tareas_p if t.puesto == "Facturación"))
            c2.metric("Embarques", sum(1 for t in tareas_p if t.puesto == "Embarque"))
            c3.metric("Agentes de pasaje", len({a for t in tareas_p for a in t.agentes}))
            c4.metric("Horas de pasaje sin cubrir", round(sum(t.sin_cubrir for t in tareas_p) / 60, 1))
            st.caption("Responsables: " + (", ".join(f"{k} ({' + '.join(f'{hhmm_(i)}-{hhmm_(f)}' for i, f in v)})"
                                                     for k, v in sorted(hecha["responsables"].items(),
                                                                        key=lambda x: x[1][0])) or "nadie"))
            st.dataframe([{"Desde": hhmm_(t.inicio), "Hasta": hhmm_(t.fin), "Puesto": t.puesto, "Vuelo": t.vuelo,
                           "Personas": t.plazas, "Asignados": ", ".join(t.agentes),
                           "Minutos sin cubrir": t.sin_cubrir} for t in tareas_p],
                         hide_index=True, width="stretch")
        with tempfile.TemporaryDirectory() as tmp:
            salida = Path(tmp) / f"parrilla_{dia.isoformat()}.xlsx"
            exportar(p, salida, conf.equipo_plataforma, False)
            if tareas_p:
                pasaje.anadir_hoja(salida, tareas_p, hecha["responsables"])
            st.download_button("Descargar parrilla (con tus cambios)", salida.read_bytes(), salida.name, type="primary")
