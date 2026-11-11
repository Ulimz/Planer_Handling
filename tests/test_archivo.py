from datetime import date

from planer_handling.anonimizar import Codigos, es_codigo
from planer_handling.archivo import (Archivo, desde_tabla, desde_tabla_vuelos, leer_celda, tabla,
                                     tabla_vuelos)
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada
from planer_handling.mensual import Ausencia
from planer_handling.modelos import Vuelo
from planer_handling.registro import Almacen

COLORES = {"Vacaciones": "FF00B050", "Baja laboral": "FFFF0000"}


def test_codigos_fijos_y_sin_nombres(tmp_path):
    ruta = tmp_path / "codigos.json"
    c = Codigos(ruta)
    a = c.codigo("PÉREZ LÓPEZ, ANA")
    assert a == "P0001"
    assert c.codigo("Ana Perez Lopez") == a          # el mismo nombre escrito de otra forma
    assert c.codigo("GARCÍA, LUIS") == "P0002"
    assert c.codigo("EMP045") == "EMP045"            # quien ya trae código lo conserva
    assert Codigos(ruta).codigo("perez lopez ana") == a   # y sigue igual otro día
    texto = ruta.read_text(encoding="utf-8").upper()
    assert "PEREZ" not in texto and "ANA" not in texto
    assert es_codigo("P0001") and not es_codigo("ANA")
    assert c.lista([Ausencia("GARCÍA, LUIS", date(2026, 1, 1), date(2026, 1, 2))])[0].empleado == "P0002"


def test_registro_pasa_a_codigos(tmp_path):
    c = Codigos(tmp_path / "c.json")
    al = Almacen(tmp_path / "registro")
    al.guardar_plantilla([FilaCuadrante("TL", "PEREZ, ANA", 2)])
    al.anadir("PEREZ, ANA", "TL", "Vacaciones", date(2026, 1, 5), date(2026, 1, 9))
    assert al.anonimizar(c.codigo) == 2
    assert al.plantilla() == [("P0001", "TL")]
    assert al.registros()[0].empleado == "P0001"
    assert al.anonimizar(c.codigo) == 0


def test_celdas():
    assert leer_celda("6-14", COLORES) == ([(360, 840)], "")
    assert leer_celda("06:00-10:00 / 15:00-19:00", COLORES) == ([(360, 600), (900, 1140)], "")
    assert leer_celda("22-6", COLORES) == ([(1320, 1800)], "")
    assert leer_celda("Vacaciones", COLORES) == ([], "FF00B050")
    for malo in ("hola", "6", "25-3"):
        try:
            leer_celda(malo, COLORES)
            assert False, malo
        except ValueError:
            pass


def test_cuadrante_ida_y_vuelta(tmp_path):
    dias = [date(2026, 1, 1), date(2026, 1, 2)]
    f = FilaCuadrante("TL", "P0001", 2)
    f.jornadas[dias[0]] = Jornada([(360, 840)])
    f.marcas_vacias[dias[1]] = "FF00B050"
    filas = desde_tabla(tabla([f], dias, COLORES), dias, COLORES)
    assert filas[0].jornadas[dias[0]].tramos == [(360, 840)] and filas[0].marcas_vacias == {dias[1]: "FF00B050"}
    errores = []
    registro = tabla([f], dias, COLORES)
    registro[0]["01"] = "mañana"
    desde_tabla(registro, dias, COLORES, errores)
    assert errores and "P0001" in errores[0]
    arch = Archivo(tmp_path)
    arch.guardar_cuadrante(2026, 1, filas, "programa")
    assert arch.cuadrante(2026, 1, "programa")[0].jornadas == filas[0].jornadas
    v = Vuelo(dias[0], "XX1", "LGW", 1450, "XX2", "LGW", 1500, "B738", "C1")
    arch.guardar_vuelos(2026, 1, {dias[0]: [v]})
    assert arch.vuelos(2026, 1)[dias[0]][0] == v
    assert arch.meses() == [(2026, 1, {"programa", "vuelos"})]
    vuelta = desde_tabla_vuelos(tabla_vuelos([v]), dias[0])[0]
    assert (vuelta.sta, vuelta.std, vuelta.vuelo_out) == (1450, 1500, "XX2")
