"""Pestaña "Empresa y reglas": ver y cambiar el perfil de una empresa sin tocar archivos."""
from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from planer_handling import empresas
from planer_handling.configuracion import Configuracion

CATEGORIAS = ["TL", "PB/TOW", "Operario", "Jardinero", "Hipodromo", "Mando intermedio", "Pasaje",
              "Responsable pasaje"]
COLECTIVOS = {"plataforma": "Plataforma", "jardineras": "Jardineras", "hipodromo": "Hipódromo",
              "mandos": "Mandos", "parciales": "Parciales"}
HORA = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _lista(texto) -> list[str]:
    return [x.strip() for x in str(texto or "").split(",") if x.strip() and x.strip() != "nan"]


def _numeros(texto) -> list[float]:
    return [float(x) if "." in x else int(x) for x in _lista(texto)]


def _vacio(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""


def _filas(df: pd.DataFrame) -> list[dict]:
    return [f for f in df.to_dict("records") if not _vacio(f.get(df.columns[0]))]


def mostrar(perfil: empresas.Perfil, perfiles: list[empresas.Perfil], carpeta_ejemplos: Path,
            carpeta_propias: Path) -> None:
    conf = Configuracion.cargar(perfil.ruta)
    d = copy.deepcopy(conf.datos)
    k = f"cfg_{perfil.clave}_{perfil.ruta.stat().st_mtime_ns}"     # claves nuevas al cambiar de perfil
    errores: list[str] = []

    st.subheader(empresas.nombre_de(conf, perfil.clave))
    if perfil.editable:
        padre = empresas.padre_de(perfil.ruta)
        st.caption(f"Perfil propio, guardado en este ordenador. Parte de "
                   f"«{empresas.nombre_de(Configuracion.cargar(padre), padre.stem) if padre else '—'}» "
                   "y solo guarda lo que cambia.")
    else:
        st.caption("Perfil de ejemplo: no se sobrescribe. Cambia lo que quieras y guárdalo como empresa nueva.")

    t_emp, t_tur, t_con, t_ram, t_pas, t_vac, t_fun = st.tabs(
        ["Empresa", "Turnos y rotaciones", "Contratos y convenio", "Rampa", "Pasaje", "Vacaciones", "Funciones"])

    with t_emp:
        e = d.get("empresa") or {}
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre del perfil", e.get("nombre", ""), key=f"{k}_nombre",
                               help="Por ejemplo, la empresa y el cliente: «Jet2 · Málaga».")
        cliente = c2.text_input("Cliente (aerolínea)", e.get("cliente", ""), key=f"{k}_cliente")
        convenio = st.text_input("Convenio que se aplica", e.get("convenio", ""), key=f"{k}_convenio")
        c1, c2 = st.columns(2)
        zona = c1.text_input("Zona horaria", d.get("zona_horaria", "Europe/Madrid"), key=f"{k}_zona",
                             help="Los vuelos llegan en hora Zulu y se pasan a esta hora local.")
        inicio = c2.date_input("Día 1 de las rotaciones", date.fromisoformat(str(d["inicio_ciclos"])),
                               key=f"{k}_inicio", format="DD/MM/YYYY")
        d["empresa"] = {"nombre": nombre, "cliente": cliente, "convenio": convenio}
        d["zona_horaria"], d["inicio_ciclos"] = zona, inicio

    with t_tur:
        st.markdown("**Turnos**. Marca qué colectivo puede usar cada uno.")
        filas = [{"Código": c, "Entrada": t["inicio"], "Salida": t["fin"],
                  **{n: c in d.get(f"turnos_{col}", []) for col, n in COLECTIVOS.items()}}
                 for c, t in d["turnos"].items()]
        turnos = st.data_editor(pd.DataFrame(filas), num_rows="dynamic", hide_index=True, width="stretch",
                                key=f"{k}_turnos", column_config={
                                    "Entrada": st.column_config.TextColumn(help="HH:MM"),
                                    "Salida": st.column_config.TextColumn(help="HH:MM; si es menor que la entrada, "
                                                                          "acaba al día siguiente")})
        d["turnos"], usos = {}, {col: [] for col in COLECTIVOS}
        for f in _filas(turnos):
            codigo = str(f["Código"]).strip()
            if not (HORA.match(str(f["Entrada"])) and HORA.match(str(f["Salida"]))):
                errores.append(f"Turno {codigo}: la entrada y la salida van como HH:MM.")
                continue
            d["turnos"][codigo] = {"inicio": str(f["Entrada"]), "fin": str(f["Salida"])}
            for col, n in COLECTIVOS.items():
                if f.get(n) is True:
                    usos[col].append(codigo)
        for col in COLECTIVOS:
            d[f"turnos_{col}"] = usos[col]

        st.markdown("**Rotaciones**. Grupos: el día del ciclo en que empieza cada uno (A: 0, B: 3…).")
        filas = [{"Rotación": n, "Días de trabajo": r["trabajo"], "Días libres": r["libre"],
                  "Grupos": ", ".join(f"{g}: {v}" for g, v in (r.get("grupos") or {}).items())}
                 for n, r in d["rotaciones"].items()]
        rot = st.data_editor(pd.DataFrame(filas), num_rows="dynamic", hide_index=True, width="stretch",
                             key=f"{k}_rot")
        d["rotaciones"] = {}
        for f in _filas(rot):
            grupos = {}
            for par in _lista(f["Grupos"]):
                g, _, v = par.partition(":")
                if not v.strip().isdigit():
                    errores.append(f"Rotación {f['Rotación']}: los grupos van como «A: 0, B: 3».")
                    continue
                grupos[g.strip()] = int(v)
            d["rotaciones"][str(f["Rotación"])] = {"trabajo": int(f["Días de trabajo"] or 0),
                                                   "libre": int(f["Días libres"] or 0), "grupos": grupos}

    with t_con:
        cp = d.setdefault("cambios_publicado", {})
        st.markdown("**Contratos**. Jornadas: duraciones posibles de un día, en horas (2, 3, 4…). "
                    "Horas al mes: solo es un aviso en la hoja Horas.")
        filas = [{"Código": c, "Nombre": x.get("nombre", ""), "Jornadas (h)": ", ".join(map(str, x.get("jornadas_h", []))),
                  "Horas/mes mín.": (x.get("horas_mes") or [None])[0],
                  "Horas/mes máx.": (x.get("horas_mes") or [None, None])[1] if len(x.get("horas_mes") or []) > 1 else None,
                  "Horario fijo": bool(x.get("horario_fijo")), "Parcial": c in cp.get("parciales", [])}
                 for c, x in d["contratos"].items()]
        tabla = pd.DataFrame(filas)
        for col in ("Horas/mes mín.", "Horas/mes máx."):
            tabla[col] = pd.array(tabla[col], dtype="Int64")
        con = st.data_editor(tabla, num_rows="dynamic", hide_index=True, width="stretch",
                             key=f"{k}_con", column_config={
                                 "Horario fijo": st.column_config.CheckboxColumn(help="Concreción horaria: entra "
                                                                                 "siempre a su hora y no se le cambia"),
                                 "Parcial": st.column_config.CheckboxColumn(help="Se le pueden pedir horas "
                                                                            "complementarias")})
        d["contratos"], parciales = {}, []
        for f in _filas(con):
            c = {"nombre": str(f["Nombre"] or "")}
            try:
                if (j := _numeros(f["Jornadas (h)"])):
                    c["jornadas_h"] = j
            except ValueError:
                errores.append(f"Contrato {f['Código']}: las jornadas van como números separados por comas.")
            horas = [int(f[n]) for n in ("Horas/mes mín.", "Horas/mes máx.") if not _vacio(f[n])]
            if horas:
                c["horas_mes"] = horas
            if f["Horario fijo"] is True:
                c["horario_fijo"] = True
            d["contratos"][str(f["Código"])] = c
            if f["Parcial"] is True:
                parciales.append(str(f["Código"]))
        codigos = list(d["contratos"])
        actual = d.get("contrato_parcial_por_defecto")
        d["contrato_parcial_por_defecto"] = st.selectbox(
            "Contrato de quien no aparece en la lista de contratos y hace jornadas cortas", codigos,
            codigos.index(actual) if actual in codigos else 0, key=f"{k}_pdef")

        st.markdown("**Cambios en un cuadrante ya publicado** (bajas y reorganizaciones)")
        c1, c2 = st.columns(2)
        cp["parciales"] = parciales
        cp["preaviso_complementarias_dias"] = c1.number_input(
            "Preaviso para cambiar a un parcial (días)", 0, 30, int(cp.get("preaviso_complementarias_dias", 3)),
            key=f"{k}_prec", help="Con este preaviso se usan las horas complementarias pactadas.")
        pc = cp.get("preaviso_horario_completo_dias")
        prev_tc = c2.number_input("Preaviso para mover el horario de un tiempo completo (días, 0 = sin mínimo)",
                                  0, 30, int(pc or 0), key=f"{k}_pretc",
                                  help="Con menos preaviso solo se le puede llamar como perentorias.")
        cp["preaviso_horario_completo_dias"] = prev_tc or None
        cp["complementarias_especiales"] = c1.toggle(
            "Permitir horas complementarias especiales (con menos preaviso)",
            bool(cp.get("complementarias_especiales")), key=f"{k}_esp")
        if cp["complementarias_especiales"]:
            cp["complementarias_especiales_mes_h"] = c2.number_input(
                "Máximo de complementarias especiales al mes (h)", 0, 100,
                int(cp.get("complementarias_especiales_mes_h", 20)), key=f"{k}_espmes")

    with t_ram:
        s = d["servicio"]
        st.markdown("**Ventana de trabajo del equipo** (minutos respecto a la llegada STA y la salida STD)")
        c1, c2, c3 = st.columns(3)
        s["giro"]["antes_sta"] = c1.number_input("Giro: antes de la llegada", 0, 180, int(s["giro"]["antes_sta"]), key=f"{k}_g1")
        s["giro"]["despues_std"] = c1.number_input("Giro: después de la salida", 0, 180, int(s["giro"]["despues_std"]), key=f"{k}_g2")
        s["solo_salida"]["antes_std"] = c2.number_input("Solo salida: antes", 0, 240, int(s["solo_salida"]["antes_std"]), key=f"{k}_s1")
        s["solo_salida"]["despues_std"] = c2.number_input("Solo salida: después", 0, 180, int(s["solo_salida"]["despues_std"]), key=f"{k}_s2")
        s["solo_llegada"]["antes_sta"] = c3.number_input("Solo llegada: antes", 0, 180, int(s["solo_llegada"]["antes_sta"]), key=f"{k}_l1")
        s["solo_llegada"]["despues_sta"] = c3.number_input("Solo llegada: después", 0, 240, int(s["solo_llegada"]["despues_sta"]), key=f"{k}_l2")
        s["transito_entre_vuelos"] = c1.number_input("Tránsito entre dos vuelos", 0, 120, int(s["transito_entre_vuelos"]), key=f"{k}_tr")
        st.markdown("**Equipo de plataforma**, en orden: el primero es el jefe de equipo y el segundo el pushback.")
        eq = st.data_editor(pd.DataFrame({"Puesto": d["equipo_plataforma"]}), num_rows="dynamic", hide_index=True,
                            key=f"{k}_eq")
        d["equipo_plataforma"] = [str(f["Puesto"]) for f in _filas(eq)]
        c1, c2 = st.columns(2)
        tp = d.setdefault("tl_pb_como_operario", {"permitido": True, "coste": 100})
        tp["permitido"] = c1.toggle("Un TL o PB que sobra puede hacer de operario", bool(tp.get("permitido")),
                                    key=f"{k}_tlpb", help="Solo si hace falta; si no, queda de refuerzo.")
        d["solape_minimo_equipo"] = c2.number_input("Coincidencia mínima para formar equipo (min)", 0, 600,
                                                    int(d.get("solape_minimo_equipo", 120)), key=f"{k}_sol")
        j = d["jardineras"]
        st.markdown("**Jardineras** (autobuses a remoto)")
        c1, c2, c3 = st.columns(3)
        j["llegada"]["hasta_sta"] = c1.number_input("Llegada: hasta después de STA", 0, 120, int(j["llegada"]["hasta_sta"]), key=f"{k}_j1")
        j["salida"]["antes_std"] = c2.number_input("Salida: desde antes de STD", 0, 180, int(j["salida"]["antes_std"]), key=f"{k}_j2")
        j["salida"]["hasta_antes_std"] = c3.number_input("Salida: hasta antes de STD", 0, 120, int(j["salida"]["hasta_antes_std"]), key=f"{k}_j3")

    with t_pas:
        p = d.setdefault("pasaje", {})
        p["activo"] = st.toggle("Planificar pasaje (facturación, embarque y puestos fijos)", bool(p.get("activo")),
                                key=f"{k}_pact")
        fac, emb = p.setdefault("facturacion", {}), p.setdefault("embarque", {})
        c1, c2 = st.columns(2)
        c1.markdown("**Facturación**, por vuelo")
        fac["personas"] = c1.number_input("Personas", 0, 20, int(fac.get("personas", 4)), key=f"{k}_fp")
        fac["abre_antes_std"] = c1.number_input("Abre (min antes de la salida)", 0, 360, int(fac.get("abre_antes_std", 150)), key=f"{k}_fa")
        fac["cierra_antes_std"] = c1.number_input("Cierra (min antes de la salida)", 0, 180, int(fac.get("cierra_antes_std", 40)), key=f"{k}_fc")
        c2.markdown("**Embarque**, por puerta y vuelo")
        emb["personas"] = c2.number_input("Personas ", 0, 10, int(emb.get("personas", 2)), key=f"{k}_ep")
        emb["desde_antes_std"] = c2.number_input("Desde (min antes de la salida)", 0, 180, int(emb.get("desde_antes_std", 45)), key=f"{k}_ed")
        emb["hasta_antes_std"] = c2.number_input("Hasta (min antes de la salida)", 0, 60, int(emb.get("hasta_antes_std", 0)), key=f"{k}_eh")
        st.markdown("**Puestos fijos** mientras dura la operación")
        pf = st.data_editor(pd.DataFrame([{"Puesto": n, "Personas": v} for n, v in (p.get("puestos_fijos") or {}).items()]
                                         or [{"Puesto": None, "Personas": None}]),
                            num_rows="dynamic", hide_index=True, key=f"{k}_pf")
        p["puestos_fijos"] = {str(f["Puesto"]): int(f["Personas"] or 0) for f in _filas(pf)}
        p["responsables_a_la_vez"] = st.number_input("Responsables de pasaje a la vez", 0, 10,
                                                     int(p.get("responsables_a_la_vez", 1)), key=f"{k}_rv")

    with t_vac:
        v = d.setdefault("vacaciones", {})
        c1, c2, c3 = st.columns(3)
        v["periodos_por_persona"] = c1.number_input("Quincenas por persona", 1, 6, int(v.get("periodos_por_persona", 2)), key=f"{k}_vp")
        v["puntos_por_defecto"] = c2.number_input("Puntos de una quincena normal", 0, 100, int(v.get("puntos_por_defecto", 2)), key=f"{k}_vd")
        v["cupo_por_defecto"] = c3.number_input("Cupo normal (% de cada función)", 1, 100,
                                                round(float(v.get("cupo_por_defecto", 0.1)) * 100), key=f"{k}_vc") / 100
        st.markdown("**Temporadas**. Quincenas como JUL-1 (1 al 15) y JUL-2 (16 a fin de mes).")
        tem = st.data_editor(pd.DataFrame([{"Temporada": t["nombre"], "Quincenas": ", ".join(t["periodos"]),
                                            "Puntos": t["puntos"], "Cupo (%)": round(t.get("cupo", v["cupo_por_defecto"]) * 100)}
                                           for t in v.get("temporadas", [])]),
                             num_rows="dynamic", hide_index=True, width="stretch", key=f"{k}_tem")
        v["temporadas"] = []
        for f in _filas(tem):
            quincenas = [q.upper() for q in _lista(f["Quincenas"])]
            if any(not re.match(r"^[A-Z]{3}-[12]$", q) for q in quincenas):
                errores.append(f"Temporada {f['Temporada']}: las quincenas van como JUL-1, AGO-2…")
            v["temporadas"].append({"nombre": str(f["Temporada"]), "periodos": quincenas,
                                    "puntos": int(f["Puntos"] or 0), "cupo": float(f["Cupo (%)"] or 0) / 100})

    with t_fun:
        st.markdown("**Funciones** tal como aparecen en el cuadrante (columna de función) y qué pueden hacer.")
        fun = st.data_editor(pd.DataFrame([{"Función": n, "Categoría": f["categoria"],
                                            "Puede hacer": ", ".join(f.get("habilitaciones", []))}
                                           for n, f in d["funciones"].items()]),
                             num_rows="dynamic", hide_index=True, width="stretch", key=f"{k}_fun",
                             column_config={"Categoría": st.column_config.SelectboxColumn(options=CATEGORIAS, required=True)})
        d["funciones"] = {str(f["Función"]): {"categoria": f["Categoría"], "habilitaciones": _lista(f["Puede hacer"])}
                          for f in _filas(fun)}

    st.divider()
    for e in errores:
        st.error(e)
    c1, c2, c3 = st.columns([1, 2, 1])
    if perfil.editable and c1.button("Guardar cambios", type="primary", disabled=bool(errores), key=f"{k}_g"):
        empresas.guardar(d, empresas.padre_de(perfil.ruta) or carpeta_ejemplos / "base.yaml", carpeta_propias, perfil.clave)
        _listo(perfil.clave, "Cambios guardados.")
    nuevo = c2.text_input("Guardar como empresa nueva", placeholder="Nombre, por ejemplo «Jet2 · Málaga»",
                          key=f"{k}_nuevo", label_visibility="collapsed")
    if c3.button("Guardar como empresa nueva", disabled=bool(errores) or not nuevo.strip(), key=f"{k}_gn",
                 type="secondary" if perfil.editable else "primary"):
        clave = empresas.clave_de(nuevo)
        if any(x.clave == clave for x in perfiles):
            st.error("Ya hay un perfil con ese nombre.")
        else:
            d["empresa"]["nombre"] = nuevo.strip()
            padre = perfil.ruta if not perfil.editable else (empresas.padre_de(perfil.ruta) or perfil.ruta)
            empresas.guardar(d, padre, carpeta_propias, clave)
            _listo(clave, f"Guardada «{nuevo.strip()}». Ya está elegida en la barra lateral.")
    if st.session_state.pop("cfg_aviso", None):
        st.success(st.session_state.pop("cfg_texto", ""))

    with st.expander("Pasar el perfil a otro ordenador"):
        st.download_button("Descargar este perfil", yaml.safe_dump(conf.datos, allow_unicode=True, sort_keys=False),
                           f"{perfil.clave}.yaml", key=f"{k}_dl")
        subido = st.file_uploader("Cargar un perfil (.yaml)", type=["yaml", "yml"], key=f"{k}_up")
        if subido and st.button("Añadir este perfil", key=f"{k}_add"):
            datos = yaml.safe_load(subido.getvalue()) or {}
            datos.pop("hereda", None)
            clave = empresas.clave_de((datos.get("empresa") or {}).get("nombre") or Path(subido.name).stem)
            empresas.guardar(datos, carpeta_ejemplos / "base.yaml", carpeta_propias, clave)
            _listo(clave, "Perfil añadido.")


def _listo(clave: str, texto: str) -> None:
    st.session_state["perfil_pendiente"] = clave
    st.session_state["cfg_aviso"], st.session_state["cfg_texto"] = True, texto
    st.rerun()
