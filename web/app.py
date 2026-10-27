"""Web sencilla del planificador: subir archivos y descargar resultados.

Arranque: streamlit run web/app.py  (en Windows, doble clic en arrancar_web.bat)
Todo se calcula en este ordenador; los archivos no salen de él.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import altair as alt
import streamlit as st

from planer_handling.anual import rotaciones_recientes
from planer_handling.anual_excel import exportar_anio
from planer_handling.configuracion import Configuracion
from planer_handling.desde_cuadrante import generar_parrilla_cuadrante
from planer_handling.importar.ausencias import leer_ausencias
from planer_handling.importar.contratos import leer_contratos
from planer_handling.importar.cuadrante import leer_cuadrante
from planer_handling.importar.parrilla_real import leer_vuelos_parrilla
from planer_handling.importar.vuelos import leer_vuelos
from planer_handling.mensual import INICIO_MAS_TEMPRANO, aprender_perfiles, dias_del_mes, emparejar_giros, planificar_mes, reorganizar
from planer_handling.mensual_excel import exportar_mes
from planer_handling.parrilla_excel import exportar
from planer_handling.registro import Almacen, motivos
from planer_handling.resumen import resumir

RAIZ = Path(__file__).resolve().parent.parent
DEMO = RAIZ / "ejemplos" / "demo"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

st.set_page_config(page_title="Planificador de handling", page_icon="✈️", layout="wide")
st.title("Planificador de handling")
st.caption("Todo se calcula en este ordenador. Los archivos no se envían a ningún sitio.")
demo = st.sidebar.toggle("Demo con una empresa ficticia", value=False)
if demo:
    st.sidebar.caption("Plantilla de 287 personas, nombres y vuelos inventados (aerolínea XY). "
                       "Los archivos ya están cargados: solo hay que pulsar los botones.")
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
def configuracion() -> Configuracion:
    return Configuracion.cargar(RAIZ / "config" / "base.yaml")


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


def leer_vuelos_mes(ruta: Path, dias: list[date]) -> dict:
    return {d: v for d in dias if (v := emparejar_giros(leer_vuelos(ruta, d, conf.zona_horaria)[0]))}


conf = configuracion()
almacen = Almacen(RAIZ / "datos" / ("registro_demo" if demo else "registro"))
if demo and not almacen.plantilla():
    almacen.guardar_plantilla(leer_cuadrante(DEMO / "cuadrante_octubre_2026.xlsx", 2026))
colores = motivos(conf)
OCTUBRE_DEMO, NOVIEMBRE_DEMO = date(2026, 10, 1), date(2026, 11, 1)
resumen_tab, ausencias_tab, anual_tab, mensual_tab, diaria_tab = st.tabs(
    ["Resumen", "Plantilla y ausencias", "Rotaciones del año", "Cuadrante del mes", "Parrilla del día"])

with resumen_tab:
    st.subheader("¿Cubre el cuadrante los vuelos?")
    st.write("Sube un cuadrante (del programa o hecho a mano) y los vuelos de ese mes. Se ve, franja a franja "
             "de 15 minutos, cuánta gente hay y cuánta piden los vuelos.")
    anio_s, mes_s = elegir_mes("Mes del cuadrante", date.today().replace(day=1), "res", NOVIEMBRE_DEMO)
    cuadrante_s = archivo("Cuadrante", ["xlsx"], "cs", "cuadrante_programa_noviembre_2026.xlsx")
    vuelos_s = archivo("Vuelos del mes (Flights, PACOTRON u OMS)", ["xlsx", "xls", "csv"], "vs",
                       "vuelos_noviembre_2026.xlsx")
    otro_s = archivo("Otro cuadrante del mismo mes para comparar (opcional), por ejemplo el hecho a mano",
                     ["xlsx"], "os", "cuadrante_a_mano_noviembre_2026.xlsx")
    if st.button("Ver resumen", type="primary", disabled=not (cuadrante_s and vuelos_s)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                with st.spinner("Calculando…"):
                    dias_s = dias_del_mes(anio_s, mes_s)
                    ruta_v = guardar(vuelos_s, tmp)
                    vuelos_s = {d: leer_vuelos(ruta_v, d, conf.zona_horaria)[0] for d in dias_s}
                    st.session_state["resumen"] = resumir(leer_cuadrante(guardar(cuadrante_s, tmp), anio_s),
                                                          vuelos_s, conf, dias_s)
                    st.session_state["comparado"] = resumir(leer_cuadrante(guardar(otro_s, tmp), anio_s),
                                                            vuelos_s, conf, dias_s) if otro_s else None
            except Exception as error:
                st.error(f"No se ha podido calcular: {error}")
    resumen, comparado = st.session_state.get("resumen"), st.session_state.get("comparado")
    if resumen:
        def cifras(res):
            pedidas = sum(sum(dp.plan.demanda[r]) for dp in res for r in dp.plan.demanda) * 15 / 60
            sin = sum(r.sin_cubrir for r in res)
            return sum(r.horas for r in res), sin, 100 * (1 - sin / pedidas) if pedidas else 0.0

        def numero(x: float) -> str:
            return f"{x:,.0f}".replace(",", ".")

        horas_s, sin_cubrir, cubierto = cifras(resumen)
        diferencia = None
        if comparado:
            h2, s2, c2_ = cifras(comparado)
            diferencia = (horas_s - h2, sin_cubrir - s2, cubierto - c2_)
            st.caption(f"Comparado con el otro cuadrante: {numero(h2)} horas, {numero(s2)} sin cubrir, "
                       f"{c2_:.1f} % cubierto.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vuelos en el mes", numero(sum(r.vuelos for r in resumen)))
        c2.metric("Horas de rampa", numero(horas_s),
                  None if diferencia is None else f"{numero(diferencia[0])} h", delta_color="inverse")
        c3.metric("Necesidad cubierta", f"{cubierto:.1f} %",
                  None if diferencia is None else f"{diferencia[2]:+.1f} puntos")
        c4.metric("Horas sin cubrir", numero(sin_cubrir),
                  None if diferencia is None else f"{numero(diferencia[1])} h", delta_color="inverse")
        st.caption("Las horas sin cubrir ya cuentan que un TL o PB que sobra puede hacer de operario: "
                   f"lo hace {sum(r.tl_pb_como_operario for r in resumen):,.0f} horas en el mes.".replace(",", "."))

        c1, c2 = st.columns([2, 1])
        dia_s = c1.select_slider("Día", [r.dia for r in resumen], format_func=lambda d: f"{d:%d/%m}", key="dia_s")
        rol = c2.radio("Puesto", ["Operario", "TL", "PB/TOW"], horizontal=True, key="rol_s")
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
        escala = alt.Scale(domain=["En el cuadrante", "Piden los vuelos"], range=["#2a78d6", "#eb6834"])
        fin_eje = INICIO_MAS_TEMPRANO / 60 + ultima / 4
        base = alt.Chart(alt.Data(values=filas_g)).encode(
            x=alt.X("Hora:Q", title=None, scale=alt.Scale(domain=[INICIO_MAS_TEMPRANO / 60, fin_eje], nice=False),
                    axis=alt.Axis(values=list(range(INICIO_MAS_TEMPRANO // 60, int(fin_eje) + 1, 2)),
                                  labelExpr="(datum.value % 24 < 10 ? '0' : '') + (datum.value % 24) + ':00'")),
            y=alt.Y("Personas:Q"), color=alt.Color("Serie:N", scale=escala, legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("Franja:N", title="Hora"), "Serie:N", "Personas:Q"])
        grafico = (base.transform_filter(alt.datum.Serie == "En el cuadrante").mark_area(opacity=0.35, interpolate="step-after")
                   + base.transform_filter(alt.datum.Serie == "Piden los vuelos").mark_line(strokeWidth=2, interpolate="step-after"))
        st.altair_chart(grafico.properties(height=320), use_container_width=True)
        with st.expander("Día a día"):
            st.dataframe([{"Día": r.dia.strftime("%d/%m"), "Vuelos": r.vuelos, "Personas": r.personas,
                           "Horas": r.horas, "Horas sin cubrir": round(r.sin_cubrir, 1),
                           "TL/PB de operario (h)": round(r.tl_pb_como_operario, 1)} for r in resumen],
                         hide_index=True)

with anual_tab:
    st.subheader("Calendario de rotaciones de un año")
    st.write("Sube el último cuadrante (y, si lo tienes, el del mes anterior). El programa sigue el ciclo de "
             "cada persona desde donde va, sin reiniciarlo en enero, y marca cada día de mañana, de tarde o libre.")
    hoy_a = date.today()
    anio_a, mes_a = elegir_mes("Mes del último cuadrante", hoy_a.replace(day=1), "an", OCTUBRE_DEMO)
    ultimo = archivo("Último cuadrante", ["xlsx"], "ua", "cuadrante_octubre_2026.xlsx")
    anterior = st.file_uploader("Cuadrante del mes anterior (opcional, da más seguridad)", type=["xlsx"], key="aa")
    anio_obj = st.number_input("Año a calcular", 2020, 2100, 2027 if demo else hoy_a.year + 1, key="anio_obj")
    if st.button("Calcular rotaciones", type="primary", disabled=not ultimo):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                meses = []
                if anterior:
                    anio_p, mes_p = (anio_a, mes_a - 1) if mes_a > 1 else (anio_a - 1, 12)
                    meses.append((leer_cuadrante(guardar(anterior, tmp), anio_p), dias_del_mes(anio_p, mes_p)))
                meses.append((leer_cuadrante(guardar(ultimo, tmp), anio_a), dias_del_mes(anio_a, mes_a)))
                rot = rotaciones_recientes(meses)
                salida = tmp / f"rotaciones_{int(anio_obj)}.xlsx"
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
             "Se guarda en este ordenador, en la carpeta datos/registro.")

    plantilla = almacen.plantilla()
    with st.expander(f"Plantilla: {len(plantilla)} personas" if plantilla else "Plantilla: aún no cargada",
                     expanded=not plantilla):
        st.write("Sube un cuadrante para sacar de él la lista de personas. Vuelve a subirlo cuando entre o salga gente.")
        cuadrante_plantilla = st.file_uploader("Cuadrante", type=["xlsx"], key="pl")
        if st.button("Guardar plantilla", disabled=not cuadrante_plantilla):
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    n = almacen.guardar_plantilla(leer_cuadrante(guardar(cuadrante_plantilla, Path(tmp)), date.today().year))
                    st.success(f"Plantilla guardada: {n} personas.")
                    st.rerun()
                except Exception as error:
                    st.error(f"No se ha podido leer el cuadrante: {error}")

    st.markdown("#### Apuntar una ausencia")
    if not plantilla:
        st.info("Primero carga la plantilla.")
    else:
        with st.form("nueva", clear_on_submit=True):
            persona = st.selectbox("Persona", plantilla, format_func=lambda p: f"{p[0]} ({p[1]})", index=None,
                                   placeholder="Escribe para buscar")
            motivo = st.selectbox("Motivo", list(colores))
            c1, c2, c3 = st.columns(3)
            desde = c1.date_input("Desde", value=date.today(), format="DD/MM/YYYY")
            abierta = c3.checkbox("Sin fecha de fin (hasta que le den el alta)", value=True)
            hasta = c2.date_input("Hasta (incluido)", value=date.today(), format="DD/MM/YYYY")
            nota = st.text_input("Nota (opcional)")
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
            st.dataframe([{"Persona": r.empleado, "Función": r.funcion, "Motivo": r.motivo,
                           "Desde": r.desde.strftime("%d/%m/%Y"),
                           "Hasta": r.hasta.strftime("%d/%m/%Y") if r.hasta else "abierta", "Nota": r.nota}
                          for r in sorted(registros, key=lambda r: r.desde, reverse=True)], hide_index=True)
            a_borrar = st.selectbox("Borrar una apuntada por error", registros, index=None,
                                    format_func=lambda r: f"{r.empleado}, {r.motivo.lower()}, {r.desde:%d/%m/%Y}")
            if st.button("Borrar", disabled=a_borrar is None):
                almacen.borrar(a_borrar.id)
                st.rerun()

    st.markdown("#### Reorganizar el cuadrante para cubrir a quien falta")
    st.write("Sube el cuadrante publicado y los vuelos del mes. El programa cambia el horario a las menos "
             "personas posibles para cubrir los huecos, y te da la lista de cambios para avisarles.")
    anio_r, mes_r = elegir_mes("Mes del cuadrante", hoy.replace(day=1), "reo", NOVIEMBRE_DEMO)
    cuadrante_r = archivo("Cuadrante publicado", ["xlsx"], "cr", "cuadrante_programa_noviembre_2026.xlsx")
    vuelos_r = archivo("Vuelos del mes (Flights, PACOTRON u OMS)", ["xlsx", "xls", "csv"], "vr",
                       "vuelos_noviembre_2026.xlsx")
    contratos_r = archivo("Contratos (recomendado): Empleado, Contrato. Según el contrato y los días de preaviso "
                          "se decide a quién se puede mover y qué tipo de horas genera.", ["xlsx", "csv"], "conr",
                          "contratos.xlsx")
    dias_r = dias_del_mes(anio_r, mes_r)
    rango = st.date_input("Días a reorganizar", value=(max(hoy, dias_r[0]) if hoy <= dias_r[-1] else dias_r[0],
                                                         min(dias_r[-1], date.fromordinal(max(hoy, dias_r[0]).toordinal() + 6))),
                          min_value=dias_r[0], max_value=dias_r[-1], format="DD/MM/YYYY", key="rango")
    aviso_r = st.date_input("Día en que se avisa de los cambios", value=NOVIEMBRE_DEMO if demo else hoy,
                            format="DD/MM/YYYY", key="aviso_r_demo" if demo else "aviso_r",
                            help="Con 3 días o más de preaviso, a un parcial se le aplica el pacto de horas "
                                 "complementarias; con menos, horas complementarias especiales (máx. 20 h al mes).")
    con_nombres_r = st.checkbox("Mostrar nombres (si no, solo códigos)", value=True, key="nmr")
    if st.button("Reorganizar", type="primary", disabled=not (cuadrante_r and vuelos_r and len(rango) == 2)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                with st.status("Leyendo archivos…") as estado:
                    filas = leer_cuadrante(guardar(cuadrante_r, tmp), anio_r)
                    elegidos = [d for d in dias_r if rango[0] <= d <= rango[1]]
                    vuelos = leer_vuelos_mes(guardar(vuelos_r, tmp), elegidos)
                    estado.update(label=f"{len(filas)} personas y {sum(map(len, vuelos.values()))} vuelos. "
                                        "Reorganizando día a día…")
                    barra = st.progress(0.0)
                    contratos = leer_contratos(guardar(contratos_r, tmp)) if contratos_r else None
                    cm, cambios = reorganizar(filas, dias_r, vuelos, almacen.ausencias(), conf, 20,
                                              progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"),
                                              contratos=contratos, aviso=aviso_r)
                    salida = tmp / f"cuadrante_reorganizado_{anio_r}-{mes_r:02d}.xlsx"
                    exportar_mes(cm, salida, con_nombres_r, colores, cambios)
                    estado.update(label="Reorganización lista", state="complete")
                st.download_button("Descargar cuadrante reorganizado", salida.read_bytes(), salida.name, type="primary")
                if cambios:
                    st.dataframe([{"Día": c.dia.strftime("%d/%m"), "Persona": c.empleado, "Función": c.funcion,
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
    st.write("Sube los vuelos del mes y el cuadrante de un mes anterior. El programa continúa la rotación "
             "de cada persona y le pone el horario que mejor cubre los vuelos de cada día.")
    hoy = date.today()
    siguiente = date(hoy.year + hoy.month // 12, hoy.month % 12 + 1, 1)
    anio, mes = elegir_mes("A planificar", siguiente, "plan", NOVIEMBRE_DEMO)
    vuelos_mes = archivo("Vuelos del mes (Flights, PACOTRON u OMS)", ["xlsx", "xls", "csv"], "vm",
                         "vuelos_noviembre_2026.xlsx")
    referencia = archivo("Cuadrante de referencia (normalmente el del mes anterior)", ["xlsx"], "ref",
                         "cuadrante_octubre_2026.xlsx")
    anio_ref, mes_ref = elegir_mes("Mes del cuadrante de referencia", hoy.replace(day=1), "ref", OCTUBRE_DEMO)
    ausencias_archivo = st.file_uploader("Ausencias del mes (opcional): Empleado, Desde, Hasta, Motivo",
                                         type=["xlsx", "csv"], key="aus")
    contratos_archivo = archivo("Contratos (opcional): Empleado, Contrato. A los parciales se les "
                                "ajustan las horas a los vuelos; a los TC se les dan sus 8 horas.",
                                ["xlsx", "csv"], "con", "contratos.xlsx")
    st.caption("Las ausencias apuntadas en la pestaña Plantilla y ausencias se tienen en cuenta solas.")
    con_nombres = st.checkbox("Mostrar nombres (si no, solo códigos)", value=True, key="nm")
    segundos = st.slider("Tiempo de cálculo por día (segundos)", 10, 60, 30, key="seg")

    if st.button("Generar cuadrante", type="primary", disabled=not (vuelos_mes and referencia)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                ruta_vuelos, ruta_ref = guardar(vuelos_mes, tmp), guardar(referencia, tmp)
                with st.status("Leyendo archivos…") as estado:
                    dias_ref = dias_del_mes(anio_ref, mes_ref)
                    contratos = leer_contratos(guardar(contratos_archivo, tmp)) if contratos_archivo else None
                    perfiles = aprender_perfiles(leer_cuadrante(ruta_ref, anio_ref), dias_ref, conf, contratos)
                    vuelos = {d: leer_vuelos(ruta_vuelos, d, conf.zona_horaria)[0] for d in dias_del_mes(anio, mes)}
                    ausencias = almacen.ausencias()
                    if ausencias_archivo:
                        ausencias += leer_ausencias(guardar(ausencias_archivo, tmp))
                    estado.update(label=f"{len(perfiles)} personas y {sum(map(len, vuelos.values()))} vuelos. "
                                        "Planificando día a día…")
                    barra = st.progress(0.0)
                    cm = planificar_mes(vuelos, perfiles, dias_ref[0], conf, segundos, ausencias,
                                        progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"))
                    salida = tmp / f"cuadrante_{anio}-{mes:02d}.xlsx"
                    exportar_mes(cm, salida, con_nombres, colores)
                    estado.update(label="Cuadrante listo", state="complete")
                st.download_button("Descargar cuadrante", salida.read_bytes(), salida.name, type="primary")
                st.dataframe([{"Día": dp.dia.strftime("%d/%m"), "Vuelos": dp.vuelos, "Personas": len(dp.jornadas),
                               "Ausentes": len(dp.ausentes),
                               "Horas sin cubrir": round(sum(dp.deficit(r) for r in dp.demanda) / 60, 1)}
                              for dp in cm.dias], hide_index=True)
            except Exception as error:  # se enseña al usuario en lugar de una traza
                st.error(f"No se ha podido generar: {error}")

with diaria_tab:
    st.subheader("Parrilla del día a partir del cuadrante")
    st.write("Sube el cuadrante del mes y los vuelos del día. El programa forma los equipos con quien "
             "coincide en horario y les asigna los vuelos.")
    dia = st.date_input("Día", value=date(2026, 11, 6) if demo else date.today(), format="DD/MM/YYYY",
                        key="dia_demo" if demo else "dia")
    cuadrante = archivo("Cuadrante del mes", ["xlsx"], "cd", "cuadrante_programa_noviembre_2026.xlsx")
    vuelos_dia = archivo("Vuelos (Flights, PACOTRON, OMS o libro de parrillas)", ["xlsx", "xls", "csv"], "vd",
                         "vuelos_noviembre_2026.xlsx")
    hoja = st.text_input("Si es un libro de parrillas, nombre de la hoja del día (por ejemplo 15-10)", key="hj")
    con_nombres_dia = st.checkbox("Mostrar nombres (si no, solo códigos)", value=True, key="nmd")

    if st.button("Generar parrilla", type="primary", disabled=not (cuadrante and vuelos_dia)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                ruta_vuelos, ruta_cuadrante = guardar(vuelos_dia, tmp), guardar(cuadrante, tmp)
                with st.spinner("Formando equipos y asignando vuelos…"):
                    if hoja:
                        vuelos, incidencias = leer_vuelos_parrilla(ruta_vuelos, hoja, dia)[0], []
                    else:
                        vuelos, incidencias = leer_vuelos(ruta_vuelos, dia, conf.zona_horaria)
                        vuelos = emparejar_giros(vuelos)
                    parrilla = generar_parrilla_cuadrante(dia, vuelos, leer_cuadrante(ruta_cuadrante, dia.year),
                                                          conf, incidencias, 20, almacen.ausencias())
                    salida = tmp / f"parrilla_{dia.isoformat()}.xlsx"
                    exportar(parrilla, salida, conf.equipo_plataforma, con_nombres_dia)
                grupos = [e for e in parrilla.reparto.equipos if e.seccion == "GRUPOS"]
                sin_equipo = sum(1 for t in parrilla.tareas if t.id not in parrilla.asignadas)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Vuelos", len(vuelos))
                c2.metric("Equipos", len(grupos))
                c3.metric("De refuerzo", len(parrilla.reparto.equipos) - len(grupos))
                c4.metric("Sin equipo", sin_equipo)
                st.download_button("Descargar parrilla", salida.read_bytes(), salida.name, type="primary")
                pendientes = [i for i in parrilla.incidencias if i.gravedad == "PENDIENTE"]
                if pendientes:
                    st.warning(f"{len(pendientes)} incidencias pendientes (detalle en la hoja Incidencias).")
            except Exception as error:
                st.error(f"No se ha podido generar: {error}")
