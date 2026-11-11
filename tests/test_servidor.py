"""Servidor central: empresas separadas, permisos por base y herramienta, contraseñas y personal."""
from datetime import date

import pytest

from planer_handling.archivo import Archivo
from planer_handling.configuracion import Configuracion
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada
from planer_handling.mensual import dias_del_mes
from planer_handling.servidor import permisos
from planer_handling.servidor.modelo import ahora
from planer_handling.servidor.personal import Filtro, estado_del_dia, fichas_de_la_base, filtrar
from planer_handling.servidor.permisos import SinPermiso
from planer_handling.servidor.servicio import ErrorDatos, Servidor

CLAVE = "clave-larga-1"


@pytest.fixture
def srv(tmp_path):
    s = Servidor(f"sqlite:///{tmp_path / 'aeros.db'}", tmp_path / "datos")
    s.crear_tablas()
    return s


@pytest.fixture
def mundo(srv):
    """Dos empresas: A con ALC y VLC, B con PMI. Una central en cada una."""
    srv.crear_admin("admin", CLAVE)
    admin = srv.usuario_de(srv.entrar("admin", CLAVE))
    a = srv.crear_empresa(admin, "empresa_a", "Empresa A")
    b = srv.crear_empresa(admin, "empresa_b", "Empresa B")
    alc = srv.crear_base(admin, a.id, "alc", "Alicante")
    vlc = srv.crear_base(admin, a.id, "VLC", herramientas=["datos", "cuadrante", "personal"])
    pmi = srv.crear_base(admin, b.id, "PMI")
    srv.crear_usuario(admin, "central.a", CLAVE, a.id, central=True)
    srv.crear_usuario(admin, "central.b", CLAVE, b.id, central=True)
    central_a = srv.usuario_de(srv.entrar("central.a", CLAVE))
    central_b = srv.usuario_de(srv.entrar("central.b", CLAVE))
    return dict(admin=admin, a=a, b=b, alc=alc, vlc=vlc, pmi=pmi, central_a=central_a, central_b=central_b)


def entra(srv, usuario):
    return srv.usuario_de(srv.entrar(usuario, CLAVE))


def test_la_central_ve_todas_sus_bases_y_ninguna_de_otra_empresa(srv, mundo):
    assert [b.codigo for b in srv.bases_visibles(mundo["central_a"])] == ["ALC", "VLC"]
    assert [b.codigo for b in srv.bases_visibles(mundo["central_b"])] == ["PMI"]
    with pytest.raises(SinPermiso):
        srv.base(mundo["central_a"], mundo["pmi"].id)
    with pytest.raises(SinPermiso):
        srv.carpeta_base(mundo["central_a"], srv.base(mundo["central_b"], mundo["pmi"].id))


def test_el_administrador_de_aeros_no_entra_en_los_datos_de_las_bases(srv, mundo):
    assert srv.bases_visibles(mundo["admin"]) == []
    assert not permisos.puede(mundo["admin"], mundo["alc"], "cuadrante")


def test_solo_el_administrador_crea_empresas_y_bases(srv, mundo):
    with pytest.raises(SinPermiso):
        srv.crear_empresa(mundo["central_a"], "otra", "Otra")
    with pytest.raises(SinPermiso):
        srv.crear_base(mundo["central_a"], mundo["a"].id, "BCN")


def test_permisos_por_base_rol_y_herramienta(srv, mundo):
    c = mundo["central_a"]
    u = srv.crear_usuario(c, "jefe.alc", CLAVE)
    srv.dar_acceso(c, u.id, mundo["alc"].id, "jefe_base")
    srv.dar_acceso(c, u.id, mundo["vlc"].id, "consulta")
    jefe = entra(srv, "jefe.alc")
    alc, vlc = srv.base(jefe, mundo["alc"].id), srv.base(jefe, mundo["vlc"].id)
    assert permisos.puede(jefe, alc, "parrilla", cambiar=True)
    assert permisos.puede(jefe, vlc, "cuadrante") and not permisos.puede(jefe, vlc, "cuadrante", cambiar=True)
    assert not permisos.puede(jefe, vlc, "parrilla")              # VLC no tiene parrilla contratada
    assert not permisos.cambia_reglas(jefe)

    p = srv.crear_usuario(c, "planif.alc", CLAVE)
    srv.dar_acceso(c, p.id, mundo["alc"].id, "planificador", ["cuadrante", "parrilla"])
    planif = entra(srv, "planif.alc")
    assert set(permisos.herramientas(planif, alc)) == {"cuadrante", "parrilla"}
    assert [b.codigo for b in srv.bases_visibles(planif)] == ["ALC"]

    srv.quitar_acceso(c, u.id, mundo["vlc"].id)
    assert [b.codigo for b in srv.bases_visibles(srv.usuario_de(srv.entrar("jefe.alc", CLAVE)))] == ["ALC"]


def test_la_central_no_toca_usuarios_ni_bases_de_otra_empresa(srv, mundo):
    otro = srv.crear_usuario(mundo["central_b"], "jefe.pmi", CLAVE)
    with pytest.raises(SinPermiso):
        srv.dar_acceso(mundo["central_a"], otro.id, mundo["pmi"].id, "jefe_base")
    mio = srv.crear_usuario(mundo["central_a"], "jefe.vlc", CLAVE)
    with pytest.raises(SinPermiso):
        srv.dar_acceso(mundo["central_a"], mio.id, mundo["pmi"].id, "jefe_base")
    assert {u.usuario for u in srv.usuarios(mundo["central_a"])} == {"central.a", "jefe.vlc"}


def test_un_jefe_de_base_no_crea_usuarios(srv, mundo):
    u = srv.crear_usuario(mundo["central_a"], "jefe.alc", CLAVE)
    srv.dar_acceso(mundo["central_a"], u.id, mundo["alc"].id, "jefe_base")
    with pytest.raises(SinPermiso):
        srv.crear_usuario(entra(srv, "jefe.alc"), "nuevo", CLAVE)


def test_empresa_o_base_bloqueada_deja_de_verse(srv, mundo):
    srv.cambiar_base(mundo["admin"], mundo["vlc"].id, activa=False)
    assert [b.codigo for b in srv.bases_visibles(entra(srv, "central.a"))] == ["ALC"]
    srv.activar_empresa(mundo["admin"], mundo["a"].id, False)
    assert srv.bases_visibles(entra(srv, "central.a")) == []


def test_contrasenas_bloqueo_y_sesiones(srv, mundo):
    with pytest.raises(ErrorDatos, match="al menos"):
        srv.crear_usuario(mundo["central_a"], "corta", "abc123")
    for _ in range(5):
        with pytest.raises(ErrorDatos, match="incorrectos"):
            srv.entrar("central.a", "mal-mal-mal-1")
    with pytest.raises(ErrorDatos, match="Demasiados intentos"):
        srv.entrar("central.a", CLAVE)
    with pytest.raises(ErrorDatos, match="incorrectos"):
        srv.entrar("no.existe", CLAVE)                     # mismo mensaje: no se sabe si existe
    token = srv.entrar("central.b", CLAVE)
    assert srv.usuario_de(token).usuario == "central.b"
    srv.salir(token)
    assert srv.usuario_de(token) is None
    assert srv.usuario_de("inventado") is None


def test_desactivar_un_usuario_cierra_sus_sesiones(srv, mundo):
    u = srv.crear_usuario(mundo["central_a"], "jefe.alc", CLAVE)
    token = srv.entrar("jefe.alc", CLAVE)
    srv.activar_usuario(mundo["central_a"], u.id, False)
    assert srv.usuario_de(token) is None
    with pytest.raises(ErrorDatos):
        srv.entrar("jefe.alc", CLAVE)


def test_registro_de_lo_que_se_hace(srv, mundo):
    srv.crear_usuario(mundo["central_a"], "jefe.alc", CLAVE)
    acciones_a = {x.accion for x in srv.registro(mundo["central_a"])}
    assert {"crear_usuario", "entrar"} <= acciones_a
    assert all(x.empresa_id == mundo["a"].id for x in srv.registro(mundo["central_a"]))


def _cuadrante_6x3(codigos, anio=2026, mes=11):
    dias = dias_del_mes(anio, mes)
    filas = []
    for n, (codigo, funcion, desfase) in enumerate(codigos, 2):
        f = FilaCuadrante(funcion, codigo, n)
        for i, d in enumerate(dias):
            if (i + desfase) % 9 < 6:
                f.jornadas[d] = Jornada([(360, 840)] if (i + desfase) % 9 < 3 else [(840, 1320)])
        filas.append(f)
    return filas


def test_personal_por_codigo_y_filtro(srv, mundo, tmp_path):
    conf = Configuracion.cargar("config/base.yaml")
    c = mundo["central_a"]
    alc = srv.base(c, mundo["alc"].id)
    arch = Archivo(srv.carpeta_base(c, alc) / "archivo")
    arch.guardar_cuadrante(2026, 11, _cuadrante_6x3([("P0001", "TL", 0), ("P0002", "PCP", 3), ("P0003", "TOW/JAR", 6)]))
    arch.guardar_contratos({"P0001": "TC", "P0002": "TP", "P0003": "TP"})
    fichas = fichas_de_la_base(arch, conf)
    assert all(f["rotacion"] == "6x3" for f in fichas)
    assert srv.guardar_personal(c, alc, fichas) == 3

    personas = srv.personal(c)
    assert [p.codigo for p in personas] == ["P0001", "P0002", "P0003"]
    base_de = lambda p: p.base.codigo  # noqa: E731
    assert [p.codigo for p in filtrar(personas, Filtro(contratos=["TP"]), base_de)] == ["P0002", "P0003"]
    assert [p.codigo for p in filtrar(personas, Filtro(capacitaciones=["PB/TOW"]), base_de)] == ["P0003"]
    assert [p.codigo for p in filtrar(personas, Filtro(bases=["VLC"]), base_de)] == []

    p1 = personas[0]
    assert estado_del_dia(p1, date(2026, 11, 1), arch) == "Trabaja 06:00-14:00"
    assert estado_del_dia(p1, date(2026, 11, 7), arch) == "Libra"
    assert estado_del_dia(p1, date(2026, 12, 1), arch).endswith("según su rotación)")

    assert srv.personal(mundo["central_b"]) == []               # otra empresa no ve nada
    u = srv.crear_usuario(c, "consulta.alc", CLAVE)
    srv.dar_acceso(c, u.id, mundo["alc"].id, "consulta", ["cuadrante"])
    assert srv.personal(entra(srv, "consulta.alc")) == []       # sin la herramienta «personal»
    with pytest.raises(SinPermiso):
        srv.guardar_personal(entra(srv, "consulta.alc"), alc, fichas)
