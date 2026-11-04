from datetime import date

import pandas as pd
import pytest

from planer_handling.importar.vuelos import desfase_utc, leer_vuelos


def test_desfase_verano_e_invierno():
    assert desfase_utc(date(2027, 7, 15), "Europe/Madrid") == 120
    assert desfase_utc(date(2027, 1, 15), "Europe/Madrid") == 60
    assert desfase_utc(date(2027, 1, 15), "Atlantic/Canary") == 0


def test_pacotron_pasa_zulu_a_local_y_cruza_medianoche(tmp_path):
    ruta = tmp_path / "vuelos.xlsx"
    pd.DataFrame([
        {"FLIGHT DATE.": "15/07/2027", "FLIGHT IN": "", "ORIG": "", "STA": "", "FLIGHT OUT": "XX1000",
         "DEST": "STN", "STD": "04:00", "STAND": "C01"},
        {"FLIGHT DATE.": "15/07/2027", "FLIGHT IN": "XX1001", "ORIG": "BGY", "STA": "21:50",
         "FLIGHT OUT": "XX1002", "DEST": "DUB", "STD": "22:15", "STAND": "R03"},
        {"FLIGHT DATE.": "16/07/2027", "FLIGHT IN": "XX9999", "ORIG": "BGY", "STA": "10:00",
         "FLIGHT OUT": "", "DEST": "", "STD": "", "STAND": ""},
    ]).to_excel(ruta, index=False)
    vuelos, incidencias = leer_vuelos(ruta, date(2027, 7, 15))
    assert incidencias == []
    assert [v.codigo for v in vuelos] == ["XX1000", "XX1001/XX1002"]
    assert vuelos[0].std == 6 * 60
    giro = vuelos[1]
    assert (giro.sta, giro.std) == (23 * 60 + 50, 24 * 60 + 15)
    assert giro.remoto and not vuelos[0].remoto


def test_oms_con_horas_hhmm_y_csv(tmp_path):
    ruta = tmp_path / "oms.csv"
    ruta.write_text(
        "Flight Date;Arrivals - Flt.No.;Prev Prt;STA;Departures - Flt.No.;Next Prt;STD\n"
        "15/07/2027;XX2000;MAN;0930;XX2001;EDI;0955\n"
        "15/07/2027;XX2002;MAN;99:99;;;\n",
        encoding="utf-8",
    )
    vuelos, incidencias = leer_vuelos(ruta, date(2027, 7, 15), horas_utc=False)
    assert (vuelos[0].sta, vuelos[0].std) == (570, 595)
    assert [i.codigo for i in incidencias] == ["VUELO_HORA_INVALIDA", "VUELO_INCOMPLETO"]


def test_sin_cabecera_reconocible(tmp_path):
    ruta = tmp_path / "otro.xlsx"
    pd.DataFrame([{"A": 1}]).to_excel(ruta, index=False)
    with pytest.raises(ValueError, match="PACOTRON u OMS"):
        leer_vuelos(ruta, date(2027, 7, 15))


def test_avion_que_pasa_la_noche_no_es_un_giro(tmp_path):
    ruta = tmp_path / "vuelos.xlsx"
    pd.DataFrame([
        {"FLIGHT DATE.": "15/07/2027", "FLIGHT IN": "XX1001", "ORIG": "MAN", "STA": "09:50",
         "FLIGHT OUT": "XX1002", "DEST": "KIR", "STD": "07:35", "STAND": "C01"},
    ]).to_excel(ruta, index=False)
    vuelos, _ = leer_vuelos(ruta, date(2027, 7, 15))
    assert [(v.codigo, v.sta, v.std) for v in vuelos] == [("XX1002", None, 9 * 60 + 35),
                                                          ("XX1001", 11 * 60 + 50, None)]
