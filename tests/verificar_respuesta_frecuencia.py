"""La forma de la respuesta de frecuencia: lo que tiene que pasar DESPUES
del nadir.

Existe por un defecto que estuvo en las figuras del informe sin que ningun
test lo viera: ante 3.000 MW en la punta, la frecuencia bajaba a 49,0 Hz,
disparaba un escalon de 6.010 MW -el 15 % de la demanda- y subia hasta
51,46 Hz, para quedarse en 50,19 sin volver nunca a 50. Tres causas, y cada
test de aqui vigila una:

  1. el regulador primario era un unico retardo de 8 s, sin la fraccion de
     la turbina que responde al instante: llegaba tarde y el nadir rozaba
     el umbral de 49,0 Hz por milesimas;
  2. no habia reduccion de generacion por sobrefrecuencia (LFSM-O, que el
     Reglamento UE 2016/631 exige a toda la generacion);
  3. no habia regulacion secundaria, asi que la frecuencia se quedaba donde
     la dejaba la primaria.

Ningun umbral sale del propio modelo: 51,5 Hz es el limite de desconexion de
generacion del mismo reglamento, y "volver a 50" es la definicion de lo que
hace la secundaria.
"""
import logging
import warnings

warnings.filterwarnings('ignore')
logging.disable(logging.WARNING)

import pypsa

from iberia import config
from iberia import dinamica_frecuencia as din


def _sis(red):
    return din.Sistema(pypsa.Network(config.red_de(red)))


def _escalon(sis, mw, **kw):
    return din.simular_frecuencia(
        sis, [{'t': 0.0, 'dP_gen': float(mw)}], con_deslastre=True, **kw)


def test_sin_joroba_ante_el_evento_de_referencia():
    """3.000 MW en la punta: era el caso de la joroba de 51,46 Hz."""
    t, f, tr = _escalon(_sis('punta'), 3000.0, t_fin=120.0)
    pico = float(f.max())
    assert pico <= 50.5, (
        f"la frecuencia sube a {pico:.3f} Hz tras perder generacion. Un "
        f"sobrepico de mas de medio hercio despues del nadir solo aparece si "
        f"el deslastre corta mucho mas de lo que falta y nada lo frena.")
    print(f"OK: 3.000 MW en la punta, nadir {f.min():.3f} Hz y pico "
          f"{pico:.3f} Hz (antes del arreglo: 49,000 y 51,460)")


def test_la_secundaria_devuelve_la_frecuencia_a_50():
    """Con reserva suficiente, el AGC lleva la frecuencia a 50 Hz."""
    t, f, tr = _escalon(_sis('punta'), 2000.0, t_fin=180.0)
    final = float(f[-1])
    assert abs(final - 50.0) < 0.02, (
        f"tras 180 s la frecuencia esta en {final:.3f} Hz. Con 2.000 MW de "
        f"deficit y {_sis('punta').reserva:.0f} MW de reserva, la regulacion "
        f"secundaria tiene que haberla devuelto a 50 Hz.")
    print(f"OK: 2.000 MW en la punta, a los 180 s la frecuencia esta en "
          f"{final:.3f} Hz")


def test_la_sobrefrecuencia_no_llega_al_limite_de_desconexion():
    """Perder 3.000 MW de CARGA: ahora sobra generacion y la frecuencia sube.

    Sin LFSM-O solo la frena la reserva a bajar de la primaria. 51,5 Hz es
    el umbral por encima del cual el Reglamento UE 2016/631 permite que la
    generacion se desconecte: un modelo que lo cruza ante una perdida de
    carga de este tamano esta describiendo un sistema que no cumple la
    norma."""
    sis = _sis('punta')
    t, f, tr = din.simular_frecuencia(
        sis, [{'t': 0.0, 'dP_carga': -3000.0}], t_fin=120.0)
    pico = float(f.max())
    assert pico < 51.5, (
        f"perder 3.000 MW de carga lleva la frecuencia a {pico:.3f} Hz, por "
        f"encima del limite de desconexion de generacion de 51,5 Hz")
    assert abs(float(f[-1]) - 50.0) < 0.02, (
        f"y la secundaria no la devuelve a 50 Hz: {float(f[-1]):.3f} Hz")
    print(f"OK: perder 3.000 MW de carga sube la frecuencia a {pico:.3f} Hz "
          f"y vuelve a {float(f[-1]):.3f} Hz")


def test_la_secundaria_no_toca_el_nadir_ni_el_deslastre():
    """El AGC actua a los 30 s. Si tocara el nadir o los escalones, el modelo
    haria parecer al sistema mas robusto justo en lo que mide este trabajo
    (es la leccion que el modelo del STN aprendio con su propio AGC)."""
    from iberia.analisis_btm_cascada import escenario_real
    n = pypsa.Network(config.red_de('apagon'))
    sis = din.Sistema(n)
    ev = escenario_real(n, sis)
    _, _, con = din.simular_frecuencia(sis, list(ev), con_deslastre=True,
                                       con_agc=True)
    _, _, sin = din.simular_frecuencia(sis, list(ev), con_deslastre=True,
                                       con_agc=False)
    assert con['nadir'] == sin['nadir'], (con['nadir'], sin['nadir'])
    assert con['deslastre_total'] == sin['deslastre_total']
    assert ([e['disparado'] for e in con['escalones']]
            == [e['disparado'] for e in sin['escalones']])
    print(f"OK: con y sin AGC, el evento del 28-A da el mismo nadir "
          f"({con['nadir']:.3f} Hz) y el mismo deslastre "
          f"({con['deslastre_total']:.1f} MW)")


if __name__ == '__main__':
    fallos = 0
    for prueba in (test_sin_joroba_ante_el_evento_de_referencia,
                   test_la_secundaria_devuelve_la_frecuencia_a_50,
                   test_la_sobrefrecuencia_no_llega_al_limite_de_desconexion,
                   test_la_secundaria_no_toca_el_nadir_ni_el_deslastre):
        try:
            prueba()
        except (AssertionError, TypeError) as e:
            fallos += 1
            print(f"FALLA {prueba.__name__}: {type(e).__name__}: {e}")
    if fallos:
        raise SystemExit(f"{fallos} de 4 fallaron")
    print("Todas las verificaciones de la respuesta de frecuencia pasaron.")
