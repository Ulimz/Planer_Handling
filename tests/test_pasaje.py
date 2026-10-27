from datetime import date

from planer_handling import mensual, pasaje
from planer_handling.modelos import Vuelo

DIA = date(2026, 11, 6)


def _conf_pasaje(conf):
    conf.datos["pasaje"]["activo"] = True
    return conf


def test_sin_pasaje_activo_no_hay_demanda(conf):
    vuelos = [Vuelo(DIA, vuelo_in="XX1", origen="MAN", sta=600, vuelo_out="XX2", destino="MAN", std=650)]
    assert not any(any(v) for v in mensual.demanda_pasaje(vuelos, conf).values())


def test_demanda_de_pasaje_por_vuelo_y_puestos_fijos(conf):
    conf = _conf_pasaje(conf)
    vuelos = [Vuelo(DIA, vuelo_in="XX1", origen="MAN", sta=600, vuelo_out="XX2", destino="MAN", std=660)]
    d = mensual.demanda_pasaje(vuelos, conf)
    franja = lambda m: d["Pasaje"][mensual._franja(m)]
    assert franja(560) == 4 + 2 + 1        # facturando: 4 de facturación, 2 de oficina, 1 lost and found
    assert franja(630) == 2 + 2 + 1        # embarcando: 2 de embarque y los fijos
    assert d["Responsable pasaje"][mensual._franja(600)] == 1


def test_reparto_de_pasaje_con_relevo(conf):
    conf = _conf_pasaje(conf)
    conf.datos["pasaje"]["puestos_fijos"] = {}
    vuelos = [Vuelo(DIA, vuelo_out="XX2", destino="MAN", std=660)]
    tareas = pasaje.tareas_pasaje(vuelos, conf)
    # Facturación de 08:30 a 10:20 y embarque de 10:15 a 11:00. A1-A4 hasta las 09:30 y A5-A10 desde las 09:30.
    agentes = {f"A{i}": [(480, 570)] for i in range(1, 5)} | {f"A{i}": [(570, 720)] for i in range(5, 11)}
    pasaje.asignar(tareas, agentes)
    facturacion = next(t for t in tareas if t.puesto == "Facturación")
    assert len(facturacion.agentes) == 8 and facturacion.sin_cubrir == 0
    assert all(t.sin_cubrir == 0 for t in tareas)
