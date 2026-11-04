from datetime import date

import pandas as pd

from planer_handling.desde_cuadrante import empleados_desde_cuadrante
from planer_handling.importar.cuadrante import FilaCuadrante
from planer_handling.importar.habilitaciones import leer_habilitaciones


def test_formacion_por_persona_corrige_la_de_su_funcion(tmp_path, conf):
    ruta = tmp_path / "formacion.xlsx"
    # Dos bloques uno al lado del otro, con la cabecera en la fila 3 como en el Excel de Azul.
    pd.DataFrame([
        [None] * 8,
        [None, "EVE ROT1", None, None, None, None, None, "TL EVE ROT1"],
        [None, "Empleado", "CONTRATO", "PCP", "FORMACION CINTA", "FORMACION CARRETEO", None, "Empleado"],
        [None, "EMP001, ANA", "EVE", 1, 1, 0, None, "EMP003, LUIS"],
        [None, "EMP002, JUAN", "FTP", 0, "NO APTO", "N/A", None, None],
    ]).to_excel(ruta, header=False, index=False)
    fichas = leer_habilitaciones(ruta, conf)
    assert fichas["EMP001 ANA"].contrato == "EVE" and fichas["EMP002 JUAN"].contrato == "TP"
    filas = [FilaCuadrante("PCP", n, i) for i, n in enumerate(["EMP001 ANA", "EMP002 JUAN", "EMP009 EVA"])]
    empleados, _ = empleados_desde_cuadrante(filas, conf, fichas)
    hoy = date(2027, 7, 15)
    ana, juan, eva = empleados
    assert ana.habilitado("Cintero", hoy) and not ana.habilitado("Carretero", hoy)
    assert not juan.habilitado("Cintero", hoy) and not juan.habilitado("Carretero", hoy) and juan.habilitado("Operario", hoy)
    assert eva.habilitado("Carretero", hoy)   # sin ficha: lo que da su función
