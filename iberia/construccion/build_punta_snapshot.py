"""Construye el punto de operacion de PUNTA INVERNAL NOCTURNA.

Para que existe
---------------
El modelo tenia un unico punto de operacion dinamico: el del apagon del
28 de abril a las 12:33, con 18.000 MW de fotovoltaica y el termico
practicamente apagado. Todo el analisis del BTM descansaba sobre ese
instante.

Este escenario es su CONTRASTE: la punta de demanda invernal, de noche.
Sirve para una afirmacion que el modelo no podia hacer hasta ahora:

    sin sol no hay BTM fotovoltaico produciendo, asi que el evento que
    estudia esta tesis NO PUEDE OCURRIR a esa hora.

Eso convierte "mas BTM acelera el colapso" en algo mas fuerte: el riesgo
del BTM es DEPENDIENTE DE LA HORA, y la ventana peligrosa es justo la de
maxima irradiancia. Es el mismo contraste punta/diurno que usa el modelo
del STN colombiano.

Efecto secundario util: es el caso de INERCIA ALTA. Con la termica y la
hidraulica despachadas en vez de 18 GW de solar, la energia cinetica sube
mucho respecto al apagon.

El punto de operacion, y que es dato y que no
----------------------------------------------
DATO (Red Electrica de Espana, maximos anuales de demanda):
  - Maximo horario peninsular 2025: 39.957 MWh el 15 de enero, 20-21 h.
  - Punta instantanea: 40.070 MW el 15 de enero a las 20:57.
  - Fue un 4,7% superior a la del ano anterior, y sigue por debajo de los
    maximos historicos de 2007 (+11,8%) y 2021 (+5,1%, borrasca Filomena).

DATO (REE, estructura de generacion de enero, medias MENSUALES):
  eolica 31,9% · nuclear 20,7% · ciclo combinado 16,0% · hidraulica 12,9%

SUPUESTO DECLARADO, y es la limitacion principal de este escenario: esas
cuotas son MEDIAS DEL MES, no de la hora concreta. La eolica a las 21 h
de un dia de enero puede estar en cualquier sitio -es justo la tecnologia
mas variable-, asi que el reparto por tecnologia de aqui es una
construccion razonable, no una medida.

CONSECUENCIA, que hay que decir al citar cualquier cifra de este
escenario: es DERIVADO, no validado. Hereda la validacion de la RED
(topologia, parametros de linea, inercia por maquina) pero NO la del
PUNTO DE OPERACION. Mismo estatus que el escenario diurno del modelo
colombiano.

Lo que SI es solido, y es lo que justifica el escenario: a las 21 h de
enero la fotovoltaica es CERO. El sol se pone sobre las 18:10 en Madrid.
Eso no depende de ninguna media mensual.

FLUJO DE POTENCIA (corregido el 6-nov-2026). Este docstring decia que
la punta "solo sirve para la dinamica" porque su caso base daba 538,7 % de
cargabilidad y 0,75 pu de tension, y lo atribuia a las capacidades de
linea. No era eso: el dataset ponia el 37,5 % de la demanda espanola en
Madrid (REE da el 11,8 %), y a 40 GW eso eran 16 GW en Madrid. Con la
demanda repartida por comunidad autonoma (build_full_network.py) el caso
base queda en 5 sobrecargas (max 119,9 %) y Madrid a 1,01 pu, y el N-1 de
punta es citable contra esa referencia. Las 5 que quedan vienen del
despacho uniforme sin orden de merito.

No modifica iberia_scenario.nc: escribe una red nueva."""
from iberia import config
import pypsa

SALIDA = 'iberia_punta.nc'

# --- Demanda: la punta instantanea documentada por REE ---
DEMANDA_ES_MW = 40070.0

# --- Despacho objetivo por tecnologia (MW) ---
#
# Construido para cubrir los 40.070 MW mas la exportacion, con el
# criterio de que cada tecnologia opere como lo hace en una punta
# invernal nocturna:
#
#   PV y Solar Thermal   CERO. Es de noche. La termosolar con
#                        almacenamiento SI podria producir en la punta de
#                        tarde, pero a las 21 h de enero su reserva
#                        termica esta practicamente agotada y su
#                        contribucion es marginal; se pone a cero para
#                        que el escenario responda limpiamente a la
#                        pregunta "y si no hay nada de solar".
#   Nuclear              cerca de plena carga: es base y no sigue la
#                        demanda (7.408 MW instalados).
#   Pumped_storage       GENERANDO. En la punta turbina; bombea en el
#                        valle de madrugada. Es lo contrario de lo que
#                        hace en el escenario del apagon.
#   Reservoir            alta: la hidraulica de embalse es la que puntea.
#   Combined_cycle       cubre el residuo, que en una punta invernal es
#                        grande.
#   Onshore              cuota de enero de REE aplicada a la demanda.
OBJETIVO_MW = {
    'PV': 0.0,
    'Solar Thermal': 0.0,
    'Nuclear': 7000.0,
    'Pumped_storage': 5000.0,
}
OBJETIVO_EOLICA_MW = 12800.0     # ~31,9% de la demanda (cuota de enero)
OBJETIVO_HIDRO_MW = 5200.0       # Reservoir + Run_of_river, ~12,9%
OBJETIVO_CCGT_MW = 11500.0       # ciclo combinado, cubre el residuo

# Exportacion neta de Espana en este punto. En punta invernal Espana
# NO exporta 3.000 MW como en el escenario generico: con la demanda en
# maximo, el intercambio es pequeno. Se deja un valor modesto.
EXPORTACION_ES_MW = 1000.0


def escalar(n, carriers, objetivo_mw, es_gens):
    """Escala p_set de las tecnologias dadas hasta sumar objetivo_mw.

    Si el objetivo es cero se pone a cero directamente (no se puede
    escalar hacia cero con un factor)."""
    idx = es_gens[es_gens.carrier.isin(carriers)].index
    if not len(idx):
        print(f"  AVISO: ninguna maquina de {carriers}")
        return 0.0
    if objetivo_mw <= 0:
        n.generators.loc[idx, 'p_set'] = 0.0
        print(f"  {'+'.join(carriers):24s} -> {0.0:9.1f} MW (apagado)")
        return 0.0
    actual = float(n.generators.loc[idx, 'p_set'].sum())
    if actual <= 0:
        # Sin despacho previo del que escalar: se reparte proporcional a
        # la placa, que es el criterio del resto del proyecto.
        placa = n.generators.loc[idx, 'p_nom']
        n.generators.loc[idx, 'p_set'] = placa / placa.sum() * objetivo_mw
    else:
        n.generators.loc[idx, 'p_set'] *= objetivo_mw / actual
    # Nadie por encima de su placa: mismo invariante que el escenario.
    exceso = n.generators.loc[idx]
    exceso = exceso[exceso.p_set > exceso.p_nom]
    if len(exceso):
        n.generators.loc[exceso.index, 'p_set'] = n.generators.loc[
            exceso.index, 'p_nom']
        print(f"  (topados en su placa: {len(exceso)} de {carriers})")
    final = float(n.generators.loc[idx, 'p_set'].sum())
    print(f"  {'+'.join(carriers):24s} -> {final:9.1f} MW")
    return final


def main():
    n = pypsa.Network(config.red('iberia_scenario.nc'))
    es_buses = n.buses[n.buses.index.str.startswith('ES')].index
    es_gens = n.generators[n.generators.bus.isin(es_buses)]

    print("=" * 70)
    print(" PUNTA INVERNAL NOCTURNA — 15 de enero, 20-21 h")
    print(" (derivado de los maximos anuales de REE; ver el docstring)")
    print("=" * 70)

    # --- Demanda ---
    es_loads = n.loads[n.loads.bus.isin(es_buses)].index
    actual = float(n.loads.loc[es_loads, 'p_set'].sum())
    n.loads.loc[es_loads, 'p_set'] *= DEMANDA_ES_MW / actual
    print(f"\nDemanda Espana: {actual:.1f} -> {DEMANDA_ES_MW:.1f} MW "
          f"(punta instantanea REE del 15-ene-2025)")

    # --- Generacion por tecnologia ---
    print("\nDespacho por tecnologia:")
    total = 0.0
    for carrier, objetivo in OBJETIVO_MW.items():
        total += escalar(n, [carrier], objetivo, es_gens)
    total += escalar(n, ['Onshore', 'Offshore_floating'],
                     OBJETIVO_EOLICA_MW, es_gens)
    total += escalar(n, ['Reservoir', 'Run_of_river'],
                     OBJETIVO_HIDRO_MW, es_gens)
    total += escalar(n, ['Combined_cycle'], OBJETIVO_CCGT_MW, es_gens)

    # --- El resto de tecnologias, a minimo tecnico simbolico ---
    cubiertas = set(OBJETIVO_MW) | {'Onshore', 'Offshore_floating',
                                    'Reservoir', 'Run_of_river',
                                    'Combined_cycle'}
    resto = es_gens[~es_gens.carrier.isin(cubiertas)].index
    if len(resto):
        n.generators.loc[resto, 'p_set'] *= 0.01
        total += float(n.generators.loc[resto, 'p_set'].sum())

    # --- Cuadrar el balance con el ciclo combinado, que es el que regula ---
    es_gen_total = float(
        n.generators[n.generators.bus.isin(es_buses)].p_set.sum())
    objetivo_gen = DEMANDA_ES_MW + EXPORTACION_ES_MW
    desajuste = objetivo_gen - es_gen_total
    ccgt = es_gens[es_gens.carrier == 'Combined_cycle'].index
    if len(ccgt) and abs(desajuste) > 1.0:
        nuevo = float(n.generators.loc[ccgt, 'p_set'].sum()) + desajuste
        margen = float(n.generators.loc[ccgt, 'p_nom'].sum())
        if not 0 < nuevo <= margen:
            raise SystemExit(
                f"El ciclo combinado no puede cuadrar el balance: harian "
                f"falta {nuevo:.0f} MW y su placa total es {margen:.0f} MW. "
                f"Ajusta los objetivos por tecnologia.")
        escalar(n, ['Combined_cycle'], nuevo, es_gens)
        print(f"\n  (el ciclo combinado absorbe {desajuste:+.1f} MW para "
              f"cuadrar el balance)")

    # --- Resumen y comprobaciones ---
    g_es = n.generators[n.generators.bus.isin(es_buses)]
    d_es = float(n.loads[n.loads.bus.isin(es_buses)].p_set.sum())
    gen_es = float(g_es.p_set.sum())
    solar = float(g_es[g_es.carrier.isin(['PV', 'Solar Thermal'])].p_set.sum())

    print(f"\n{'='*70}")
    print(f"  demanda Espana    {d_es:10.1f} MW")
    print(f"  generacion Espana {gen_es:10.1f} MW")
    print(f"  balance           {gen_es - d_es:+10.1f} MW")
    print(f"  SOLAR             {solar:10.1f} MW   <- cero: es de noche")

    assert solar < 1.0, (
        f"la solar deberia ser cero en un escenario nocturno y vale "
        f"{solar:.1f} MW: el escenario no cumple su unico proposito")
    rotos = g_es[g_es.p_set > g_es.p_nom + 1e-6]
    assert not len(rotos), (
        f"{len(rotos)} generadores despachan por encima de su placa:\n"
        f"{rotos[['p_nom','p_set','carrier']].head().to_string()}")

    n.export_to_netcdf(config.red(SALIDA))
    print(f"\n  Guardado en data/redes/{SALIDA}")
    print("  RECORDATORIO: escenario DERIVADO, no validado. Hereda la")
    print("  validacion de la red, no la del punto de operacion.")


if __name__ == '__main__':
    main()
