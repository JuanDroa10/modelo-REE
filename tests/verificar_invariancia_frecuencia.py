"""Confirma que la compensacion reactiva (sub-proyecto G) NO movio nada
de los sub-proyectos D y E.

dinamica_frecuencia.Sistema lee p_set, p_nom, H y carrier; los shunts no
tocan ninguno, y P_carga suma loads.p_set, que tampoco cambia. Asi que
los parametros agregados y el resultado de la cascada calibrada deben
reproducir EXACTAMENTE los valores documentados. Si alguno se movio, es
un bug de G, no un resultado nuevo."""
import warnings, logging
warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

from iberia import config
import pypsa
from iberia import dinamica_frecuencia as din
from iberia.analisis_btm_cascada import escenario_real

# Valores documentados en el README y en informe/informe.txt (sub-proyecto D)
ESPERADO = {
    'P_gen': 31600.0, 'P_carga': 31800.0,
    # ENERGIA CINETICA, no H y S_base por separado.
    #
    # H y S_base NO son magnitudes fisicas independientes: son una
    # descomposicion de la energia cinetica, y la frontera entre las dos
    # depende de que entra en S_base. De los ~49.400 MVA de S_base,
    # ~34.000 son tecnologias por convertidor con H=0: engordan S_base y
    # diluyen H sin aportar un julio de inercia.
    #
    # Fijarlas por separado hacia que el test fallara por cambios que no
    # mueven la fisica. Paso de verdad: al repartir los 3.000 MW del
    # escenario de forma proporcional en vez de plana, H bajo de 1,532 a
    # 1,456 y S_base subio de 46.987 a 49.429 - y la energia cinetica se
    # quedo en 72,0 GW.s, clavada. El test habria mandado investigar una
    # regresion inexistente.
    #
    # ACTUALIZADO el 10-oct-2026, de 93,8 a 85,5: el factor de carga de
    # unidad acoplada dejo de ser un 0,70 uniforme y pasa a depender de la
    # tecnologia (FACTOR_CARGA_POR_CARRIER en dinamica_frecuencia). La
    # nuclear va a plena carga y la bomba de velocidad fija tambien, asi
    # que el 0,70 les inventaba capacidad girando; la hidraulica de
    # embalse opera mas abajo y se le quedaba corta. Desglose:
    # nuclear -8,3 | bombeo -4,5 | embalse +4,7 | resto -0,2 GW.s.
    #
    # NO es una recalibracion contra ninguna referencia externa: NO EXISTE
    # tal referencia. Los "~2,3 s de REE" contra los que este modelo se
    # validaba no aparecen en el informe de REE, ni en NERC, ni en las
    # fuentes secundarias del proyecto, y la coincidencia que se les
    # atribuia la producia el resto termico aplastado al 1%.
    'energia_cinetica_GWs': 85.5,
    # 1.965,7 -> 1.551,2 por lo mismo, y es una CORRECCION, no un efecto
    # lateral: de la reserva vieja 486 MW eran de la nuclear, que no
    # presta regulacion primaria (defecto ya levantado en la auditoria del
    # 3-oct). Con la nuclear al 0,98 su margen cae a ~69 MW.
    'reserva': 1551.2, 'exportacion': -200.0,
    # t_colapso, NO nadir. El 'nadir=47,497' que este test fijaba antes
    # era la primera muestra bajo F_COLAPSO=47,5: el truncamiento de la
    # integracion, no un minimo. Un test que congela un artefacto lo
    # protege de ser corregido - este lo protegio durante todo el
    # sub-proyecto E. La variable que discrimina entre escenarios es el
    # INSTANTE del colapso, y vale lo mismo que el viejo t_nadir porque
    # ese t_nadir era, precisamente, el instante del cruce.
    # 1,91 -> 1,81 s: con 8,3 GW.s menos de energia cinetica el sistema
    # cruza F_COLAPSO antes. Es la consecuencia esperada, no una
    # regresion; el signo es el correcto (menos inercia, colapso mas
    # rapido) y la magnitud, un 5%, es coherente con el -9% de Ek.
    # 1,81 -> 1,87 s el 4-nov-2026: la regulacion primaria pasa de un
    # retardo unico de 8 s al modelo de Anderson-Mirheydar, cuya fraccion de
    # alta presion responde al instante (ver dinamica_frecuencia). La
    # primaria llega antes, el sistema aguanta 0,06 s mas y sigue
    # COLAPSANDO: el signo es el correcto y la conclusion -el escenario
    # calibrado colapsa sin ningun BTM adicional- no cambia. La energia
    # cinetica, la reserva y el resto de este test no se mueven, como debe
    # ser: el regulador no toca el punto de operacion.
    't_colapso': 1.87,
    'P_carga_es': 27000.0,
}
TOL = {'P_gen': 0.1, 'P_carga': 0.1, 'energia_cinetica_GWs': 0.15,
       'reserva': 0.1, 'exportacion': 0.1, 't_colapso': 0.01,
       'P_carga_es': 0.1}


def main():
    n = pypsa.Network(config.red('iberia_blackout.nc'))
    sis = din.Sistema(n)
    real = {'P_gen': sis.P_gen, 'P_carga': sis.P_carga,
            'P_carga_es': sis.P_carga_es,
            'energia_cinetica_GWs': sis.H * sis.S_base / 1000.0,
            'S_base': sis.S_base, 'reserva': sis.reserva,
            'exportacion': sis.exportacion}

    _, _, traza = din.simular_frecuencia(sis, escenario_real(n, sis))
    real['t_colapso'] = traza['t_colapso']
    assert traza['colapso'], (
        'el escenario calibrado deberia COLAPSAR; si ya no colapsa, algo cambio de fondo y hay que investigarlo antes de tocar este test')
    import math
    assert math.isnan(traza['nadir']), (
        f"con colapso no hay nadir que reportar y se obtuvo "
        f"{traza['nadir']}; ver el comentario de ESPERADO")

    fallos = []
    for k, esp in ESPERADO.items():
        got = real[k]
        if abs(got - esp) > TOL[k]:
            fallos.append(f"  {k}: esperado {esp}, obtenido {got:.4f} "
                          f"(tolerancia {TOL[k]})")
        else:
            print(f"OK  {k:12s} = {got:10.4f}  (documentado {esp})")

    assert traza['colapso'], (
        "el escenario calibrado deberia seguir colapsando - si dejo de "
        "hacerlo, la compensacion movio algo que no deberia tocar")

    if fallos:
        raise SystemExit(
            "La compensacion reactiva MOVIO resultados de D/E, que no deberia "
            "tocar (Sistema no lee shunts):\n" + "\n".join(fallos))
    print("\nOK: la compensacion no movio ningun resultado de D/E.")


if __name__ == '__main__':
    main()
