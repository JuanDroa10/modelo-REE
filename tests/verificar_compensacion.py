"""Verifica la compensacion reactiva del sub-proyecto G sobre la red real."""
import warnings, logging
warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

from iberia import config
import pypsa
from iberia.construccion import add_compensacion as C
from iberia import analisis_n1 as A
from iberia import limites_reactivos_espana as L


def _red():
    return pypsa.Network(config.red('iberia_scenario.nc'))


def test_reactores_existen_y_son_inductivos():
    n = _red()
    reac = n.shunt_impedances[n.shunt_impedances.index.str.startswith(C.PREFIJO)]
    assert len(reac) > 1000, (
        f"solo {len(reac)} reactores; se esperaban ~1.225 (uno por bus con "
        f"carga capacitiva). Corre python -m iberia.construccion.add_compensacion")
    assert (reac.b < 0).all(), (
        "todo reactor debe tener b NEGATIVA (inductiva, absorbe reactivo); "
        f"hay {int((reac.b >= 0).sum())} con b >= 0")
    print(f"OK: {len(reac)} reactores, todos inductivos, "
          f"b total = {reac.b.sum():.5f} S")


def test_fraccion_es_la_declarada():
    """Cada reactor debe absorber exactamente FRACCION_COMPENSACION de la
    susceptancia capacitiva de su bus - ni mas ni menos."""
    n = _red()
    b_bus = C.susceptancia_por_bus(n)
    reac = n.shunt_impedances[n.shunt_impedances.index.str.startswith(C.PREFIJO)]
    for nombre, fila in reac.iterrows():
        bus = fila.bus
        esperado = -C.FRACCION_COMPENSACION * float(b_bus[bus])
        assert abs(float(fila.b) - esperado) < 1e-9, (
            f"{nombre}: b={fila.b:.8f} pero se esperaba {esperado:.8f} "
            f"({100*C.FRACCION_COMPENSACION:.0f}% de {b_bus[bus]:.8f})")
    print(f"OK: los {len(reac)} reactores compensan exactamente el "
          f"{100*C.FRACCION_COMPENSACION:.0f}% de su bus")


def test_el_caso_base_con_limites_queda_dentro_de_rango():
    """EL RESULTADO QUE HOY JUSTIFICA ESTE PASO.

    OJO AL LEER ESTE TEST: no comprueba que la compensacion RESUELVA
    nada. Corregido el doble conteo de `circuits` en los parametros de
    linea, el caso base con limites de Q queda dentro de rango TAMBIEN
    sin ningun reactor (f=0,00 da 0 buses fuera). Lo que aporta f=0,10 es
    MARGEN de tension, no validez: iguala la distancia a los dos limites
    (~0,02 a cada lado) frente a los 0,0028 que deja f=0,00 por arriba.

    Las cifras de 1.010 buses fuera y 14 sobrecargas que motivaron
    escribir el sub-proyecto G eran un artefacto de la susceptancia
    inflada. Ver el docstring de add_compensacion.py."""
    # SOBRE LOS DOS PUNTOS DE OPERACION PRINCIPALES (6-nov-2026), no sobre
    # el escenario generico. Al corregir el reparto de demanda (Madrid del
    # 37,5 % al 11,8 %), el generico -el de carga mas baja, 25,5 GW- deja
    # 12 barras de 400/220 kV de Ciudad Real entre 1,10 y 1,11 pu: los
    # corredores que antes iban cargados hacia Madrid van casi vacios y su
    # capacitancia levanta la tension. Es la sobretension de carga baja que
    # en la red real se resuelve conectando reactores; el modelo no
    # representa esa maniobra (f es fija). Se decidio NO ajustar f para
    # ese escenario, que es sintetico y no sostiene ningun resultado; se
    # informa abajo, sin asercion.
    for red in ('apagon', 'punta'):
        _caso_dentro_de_rango(red)
    n = _red()
    A.preparar_para_flujo_ac(n)
    _, info = L.aplicar(n, verbose=False)
    print(f"  (escenario generico, informativo: {info['v_fuera']} buses fuera, "
          f"v=[{info['v_min']:.4f}, {info['v_max']:.4f}])")


def _caso_dentro_de_rango(red):
    n = pypsa.Network(config.red_de(red))
    A.preparar_para_flujo_ac(n)
    n, info = L.aplicar(n, verbose=False)
    pct = A.cargabilidad(n)
    assert info['v_fuera'] == 0, (
        f"[{red}] "
        f"{info['v_fuera']} buses fuera de [0,9-1,1] pu en el caso base con "
        f"limites (v=[{info['v_min']:.4f}, {info['v_max']:.4f}]). Con "
        f"f={C.FRACCION_COMPENSACION} deberian ser 0; si han aparecido, "
        f"revisar si f se ha subido (a partir de 0,50 los buses se van POR "
        f"ABAJO) o si los parametros de linea han vuelto a cambiar.")
    print(f"OK [{red}]: v=[{info['v_min']:.4f}, {info['v_max']:.4f}], 0 buses fuera, "
          f"cargabilidad max {pct.max():.1f}% ({int((pct>100).sum())} sobre "
          f"100%), {len(info['conmutados'])} conmutados a PQ")


def test_el_margen_de_tension_mejora_frente_a_no_compensar():
    """La razon concreta de adoptar f=0,10 en vez de f=0,00, medida.

    Es la unica ventaja que este sub-proyecto puede reclamar hoy, asi que
    conviene que un test la sostenga en vez de un parrafo."""
    n = _red()
    sin = n.copy()
    prev = [c for c in sin.shunt_impedances.index if str(c).startswith(C.PREFIJO)]
    if prev:
        sin.remove('ShuntImpedance', prev)
    A.preparar_para_flujo_ac(sin)
    _, info0 = L.aplicar(sin, verbose=False)

    n2 = _red()
    A.preparar_para_flujo_ac(n2)
    _, infof = L.aplicar(n2, verbose=False)

    margen = lambda i: min(i['v_min'] - 0.90, 1.10 - i['v_max'])
    m0, mf = margen(info0), margen(infof)
    assert mf > m0, (
        f"compensar al {100*C.FRACCION_COMPENSACION:.0f}% deberia dar MAS "
        f"margen de tension que no compensar, y da menos: "
        f"{mf:.4f} frente a {m0:.4f}. Si esto falla, f ya no esta en su "
        f"optimo y hay que re-medir el barrido.")
    print(f"OK: margen minimo a [0,9-1,1] pu = {mf:.4f} con f="
          f"{C.FRACCION_COMPENSACION} frente a {m0:.4f} sin compensar "
          f"(+{mf - m0:.4f} pu; en el escenario generico los dos margenes "
          f"son negativos desde el reparto de demanda por comunidad)")


if __name__ == '__main__':
    test_reactores_existen_y_son_inductivos()
    test_fraccion_es_la_declarada()
    test_el_caso_base_con_limites_queda_dentro_de_rango()
    test_el_margen_de_tension_mejora_frente_a_no_compensar()
    print("\nTodas las verificaciones de compensacion pasaron.")
