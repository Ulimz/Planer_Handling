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


def _alc():
    from planer_handling.configuracion import Configuracion

    from .conftest import RAIZ
    return Configuracion.cargar(RAIZ / "config" / "azul_alc_pasaje.yaml")


def test_pasaje_de_alc_mostradores_compartidos_y_puestos_por_categoria():
    conf = _alc()
    # Nueve salidas seguidas de 10:00 a 10:40 (check-in de 07:00 a 09:59) y una de primera hora.
    vuelos = [Vuelo(DIA, vuelo_out=f"XX{i}", destino="MAN", std=600 + 5 * i) for i in range(9)]
    vuelos.append(Vuelo(DIA, vuelo_out="XX99", destino="EDI", std=7 * 60))
    d = mensual.demanda_pasaje(vuelos, conf)
    assert set(d) == {"Pasaje", "Responsable pasaje", "Operaciones pasaje", "Ticket desk", "Lost and found"}
    franja = lambda rol, m: d[rol][mensual._franja(m)]
    assert franja("Pasaje", 8 * 60) == 3 + 2 + 6          # 9 vuelos facturando: 3 + 9/4,5, y la reserva
    assert franja("Pasaje", 6 * 60 + 30) == 2 + 6         # la de las 07:00, en puerta desde las 06:00
    assert franja("Pasaje", 5 * 60 + 45) == 3 + 1 + 6     # y su check-in, abierto desde las 04:00
    assert franja("Operaciones pasaje", 8 * 60) == 2
    assert franja("Ticket desk", 8 * 60) == 1 and franja("Lost and found", 8 * 60) == 1
    assert franja("Responsable pasaje", 8 * 60) == 3
    # La parrilla del día lleva cada puesto con su categoría.
    tareas = pasaje.tareas_pasaje(vuelos, conf)
    assert {t.categoria for t in tareas if t.puesto == "Operaciones"} == {"Operaciones pasaje"}
    assert not any(t.puesto == "Oficina" and t.plazas for t in tareas)
    assert "Operaciones pasaje" in mensual.roles_planificados(conf)
