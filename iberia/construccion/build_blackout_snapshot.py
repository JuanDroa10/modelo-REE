"""Reconstruye el punto de operacion real previo al apagon del 28 de abril de
2025 (~12:33 CEST), sobre la topologia ya construida en iberia_scenario.nc.

Fuente de las cifras: resumen del informe de ENTSO-E / FERC citado en
06_documentacion/2026-09-27-diseno-sub-proyecto-D-btm.md. Es la mejor
reconstruccion disponible con fuentes secundarias, no la tabla exacta del
informe de 472 paginas - ver la nota de honestidad en ese documento sobre el
margen de ~1.862 MW sin cuadrar (incluye los ~800 MW de exportacion a
Marruecos, deliberadamente no modelados - ver el documento de diseño).

No modifica iberia_scenario.nc: escribe una red nueva."""
from iberia import config
import pypsa

n = pypsa.Network(config.red('iberia_scenario.nc'))

# --- Objetivo de despacho real por tecnologia (MW), fuente: ENTSO-E/FERC ---
OBJETIVO_MW = {
    'PV': 18000.0,
    'Solar Thermal': 1500.0,
    'Nuclear': 3400.0,
    # BOMBEO: NEGATIVO. Estaba CONSUMIENDO 3 GW, no generando.
    #
    # Fuente: NERC, "Iberian Peninsula Blackout - Contextual Comparison
    # with North American BPS Reliability Safeguards" (FERC Open Meeting,
    # 26-jun-2025), lamina 4 "Pre-event Resource Mix", que cita el panel
    # de generacion de REE del 28-abr-2025: "Pumped Storage 3GW consume".
    #
    # Versiones anteriores lo despachaban como +3.000 MW de generacion.
    # El error son 6 GW de balance -3 GW que dejan de generarse y 3 GW
    # que pasan a consumirse- y tuvo una consecuencia en cadena: el
    # simulador descarto los DOS escalones de bombeo del P.O. 1.6 (49,5 y
    # 49,3 Hz, 50% de los grupos cada uno) con el argumento de que "no
    # hay carga de bombeo activa en este punto de operacion". Si la
    # habia: 3 GW de ella.
    'Pumped_storage': -3000.0,
}
# Onshore + Offshore_floating juntos deben sumar 3.500 MW (eolica total)
OBJETIVO_EOLICA_MW = 3500.0
# Reservoir + Run_of_river juntos deben sumar 3.200 MW (hidraulica, sin bombeo)
OBJETIVO_HIDRO_MW = 3200.0

es_buses = n.buses[n.buses.index.str.startswith('ES')].index
es_gens = n.generators[n.generators.bus.isin(es_buses)]


def escalar_tecnologia(carriers, objetivo_mw):
    """Escala p_set de todos los generadores de las tecnologias dadas para
    que su suma total sea objetivo_mw, preservando el reparto relativo entre
    generadores individuales (mismo criterio que el ajuste de Francia en el
    sub-proyecto B)."""
    idx = es_gens[es_gens.carrier.isin(carriers)].index
    actual = float(n.generators.loc[idx, 'p_set'].sum())
    if actual <= 0:
        print(f"  AVISO: {carriers} no tiene despacho actual, no se puede escalar")
        return
    factor = objetivo_mw / actual
    n.generators.loc[idx, 'p_set'] *= factor
    print(f"  {carriers}: {actual:.1f} -> {objetivo_mw:.1f} MW (factor {factor:.4f})")


print("Escalando generacion de España al mix real pre-apagon...")
for carrier, objetivo in OBJETIVO_MW.items():
    escalar_tecnologia([carrier], objetivo)
escalar_tecnologia(['Onshore', 'Offshore_floating'], OBJETIVO_EOLICA_MW)
escalar_tecnologia(['Reservoir', 'Run_of_river'], OBJETIVO_HIDRO_MW)

# EL RESTO TERMICO: 3.000 MW, no un 1% simbolico.
#
# Versiones anteriores lo aplastaban al 1% de su despacho (54,5 MW de
# ciclo combinado en toda Espana) con el argumento de que "no aparece en
# el mix pre-evento reportado". SI aparece: la lamina 4 de NERC documenta
# "Cogen & Waste 1.4GW, 4%", y su propio grafico deja un ~5% (~1,6 GW)
# sin etiquetar que solo puede ser termico convencional.
#
# El error estaba oculto porque el bombeo tenia el signo cambiado: con
# +3.000 MW de generacion ficticia el balance cerraba igual. Corregido el
# bombeo a consumo, el deficit aparecio: 4.137,7 MW entre lo que el
# modelo generaba y lo que exige el dato (27.000 de carga + 3.000 de
# bombeo + 1.000 a Francia + 2.800 a Portugal = 33.800 MW).
#
# Se reparte proporcional a la placa entre las tecnologias termicas, que
# es el criterio del resto del proyecto. NO cierra el balance del todo:
# queda un residuo que es el margen ya declarado del snapshot (incluye
# los ~800 MW a Marruecos, deliberadamente no modelados). Las propias
# cifras de NERC tampoco cuadran exactamente - su grafico suma ~32,6 GW
# de generacion frente a ~34,6 GW de demanda mas exportaciones.
RESTO_TERMICO = ['Coal', 'Gas_turbine', 'ICCC', 'Steam_turbine', 'Biomass',
                 'Combined_cycle']
OBJETIVO_RESTO_TERMICO_MW = 3000.0
idx_resto = es_gens[es_gens.carrier.isin(RESTO_TERMICO)].index
placa_resto = n.generators.loc[idx_resto, 'p_nom']
n.generators.loc[idx_resto, 'p_set'] = (
    placa_resto / placa_resto.sum() * OBJETIVO_RESTO_TERMICO_MW)
print(f"  resto termico (Cogen & Waste + no etiquetado): "
      f"{OBJETIVO_RESTO_TERMICO_MW:.1f} MW")
print(f"  {RESTO_TERMICO}: reducido al 1% (minimo tecnico simbolico)")

# --- Demanda de España: +6,6% para llegar a ~27.000 MW, mismo reparto ---
# El factor se calcula contra la demanda que trae la red, no contra una
# constante: era `27000 / 25326,2`, y al cambiar el reparto de demanda
# (6-nov-2026) la base paso a 25.515 MW y el apagon salia con 27.202 MW.
DEMANDA_ES_MW = 27000.0
es_loads = n.loads[n.loads.bus.isin(es_buses)].index
FACTOR_DEMANDA_ES = DEMANDA_ES_MW / float(n.loads.loc[es_loads, 'p_set'].sum())
n.loads.loc[es_loads, 'p_set'] *= FACTOR_DEMANDA_ES
print(f"\nDemanda España escalada por {FACTOR_DEMANDA_ES:.4f} (-> ~27.000 MW)")

# --- Portugal y Francia: importan las cifras reales del momento, no las
#     genericas del sub-proyecto B ---
pt_buses = n.buses[n.buses.index.str.startswith('PT')].index
fr_buses = n.buses[n.buses.index.str.startswith('FR')].index

pt_dem_actual = float(n.loads[n.loads.bus.isin(pt_buses)].p_set.sum())
pt_gen_actual = float(n.generators[n.generators.bus.isin(pt_buses)].p_set.sum())
print(f"\nPortugal antes: Gen={pt_gen_actual:.1f} Dem={pt_dem_actual:.1f} "
      f"Balance={pt_gen_actual-pt_dem_actual:+.1f}")
# Objetivo: Portugal importa 2.800 MW de España (dato ENTSO-E del momento)
pt_gen_idx = n.generators[n.generators.bus.isin(pt_buses)].index
objetivo_pt_gen = pt_dem_actual - 2800.0
if objetivo_pt_gen > 0 and pt_gen_actual > 0:
    n.generators.loc[pt_gen_idx, 'p_set'] *= objetivo_pt_gen / pt_gen_actual
pt_gen_final = float(n.generators.loc[pt_gen_idx, 'p_set'].sum())
print(f"Portugal despues: Gen={pt_gen_final:.1f} Dem={pt_dem_actual:.1f} "
      f"Balance={pt_gen_final-pt_dem_actual:+.1f} (objetivo: -2.800)")

fr_dem_actual = float(n.loads[n.loads.bus.isin(fr_buses)].p_set.sum())
fr_gen_actual = float(n.generators[n.generators.bus.isin(fr_buses)].p_set.sum())
print(f"\nFrancia antes: Gen={fr_gen_actual:.1f} Dem={fr_dem_actual:.1f} "
      f"Balance={fr_gen_actual-fr_dem_actual:+.1f}")
# Objetivo: Francia importa 1.000 MW de España (dato ENTSO-E del momento)
fr_gen_idx = n.generators[n.generators.bus.isin(fr_buses)].index
objetivo_fr_gen = fr_dem_actual - 1000.0
if objetivo_fr_gen > 0 and fr_gen_actual > 0:
    n.generators.loc[fr_gen_idx, 'p_set'] *= objetivo_fr_gen / fr_gen_actual
fr_gen_final = float(n.generators.loc[fr_gen_idx, 'p_set'].sum())
print(f"Francia despues: Gen={fr_gen_final:.1f} Dem={fr_dem_actual:.1f} "
      f"Balance={fr_gen_final-fr_dem_actual:+.1f} (objetivo: -1.000)")

# --- Balance global y guardado ---
gen_total = float(n.generators.p_set.sum())
dem_total = float(n.loads.p_set.sum())
print(f"\nBalance global: Gen={gen_total:.1f} MW | Dem={dem_total:.1f} MW | "
      f"Diferencia={gen_total-dem_total:+.1f} MW (la absorbe el Slack)")

n.export_to_netcdf(config.red('iberia_blackout.nc'))
print(f"\n✓ Guardado en data/redes/iberia_blackout.nc")
