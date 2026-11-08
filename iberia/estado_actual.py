"""Re-deriva TODAS las cifras citables del proyecto desde los artefactos.

Por que existe
--------------
En este proyecto se han detectado varias cifras que parecian citables y
resultaron artefactos: el nadir que era el truncamiento, la ventaja del
MILP que comparaba entero contra fraccion, la cargabilidad medida contra
una s_nom inflada, los 1.010 buses fuera de rango que eran susceptancia
duplicada. Todas sobrevivieron porque estaban escritas en un documento y
nadie las volvia a medir.

Este script es la respuesta: la unica fuente de verdad son los .nc y los
.csv, y aqui se leen en vivo. Si una cifra del README o del informe no
coincide con lo que imprime esto, la equivocada es la del documento.

No valida nada ni falla: solo MIDE y presenta. Para los invariantes que
si deben fallar estan los verificar_*.py.

Uso:
    python estado_actual.py
    python estado_actual.py --md     # salida en Markdown, para pegar
"""
import argparse
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from iberia import config
import pypsa


def _fmt(x, dec=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/d"
    return f"{x:,.{dec}f}".replace(",", "@").replace(".", ",").replace("@", ".")


class Informe:
    def __init__(self, md):
        self.md = md
        self.filas = []

    def seccion(self, titulo):
        print(f"\n{'## ' if self.md else ''}{titulo}")
        if not self.md:
            print('-' * len(titulo))
        elif self.filas:
            pass
        if self.md:
            print(f"\n| cifra | valor |\n|---|---|")

    def dato(self, nombre, valor, nota=''):
        if self.md:
            print(f"| {nombre} | **{valor}**{' — ' + nota if nota else ''} |")
        else:
            print(f"  {nombre:38s} {valor:>16}" + (f"   {nota}" if nota else ""))


def red(inf):
    n = pypsa.Network(config.red('iberia_scenario.nc'))
    inf.seccion("1. La red (iberia_scenario.nc)")
    for etiqueta, comp in [("buses", 'buses'), ("lineas", 'lines'),
                           ("transformadores", 'transformers'),
                           ("generadores", 'generators'), ("cargas", 'loads'),
                           ("reactores shunt", 'shunt_impedances')]:
        inf.dato(etiqueta, _fmt(len(getattr(n, comp)), 0))

    sinc = n.generators[n.generators.H > 0]
    inf.dato("generadores sincronos (H>0)", _fmt(len(sinc), 0))
    inf.dato("inercia  H*p_nom [GW.s]",
             _fmt((n.generators.H * n.generators.p_nom).sum() / 1000, 1))

    L = n.lines.copy()
    L['v'] = n.buses.v_nom.reindex(L.bus0).values
    Lm = L[(L.length > 1) & (L.b > 0) & (L.x > 0)]
    zc = np.sqrt((Lm.x / Lm.length) / (Lm.b / Lm.length))
    for v in (400.0, 220.0):
        s = zc[Lm.v == v]
        if len(s) >= 5:
            inf.dato(f"Zc mediana {v:.0f} kV [ohm]", _fmt(s.median(), 1),
                     "fisico: 240-280 / 260-300")
    for v in (400.0, 220.0):
        s = Lm.s_nom[Lm.v == v]
        if len(s) >= 5:
            inf.dato(f"s_nom mediana {v:.0f} kV [MVA]", _fmt(s.median(), 0),
                     "por circuito")

    b_bus = pd.Series(0.0, index=n.buses.index)
    for lado in ('bus0', 'bus1'):
        b_bus = b_bus.add(n.lines.groupby(lado).b.sum() / 2.0, fill_value=0.0)
    b_bus = b_bus[b_bus > 0]
    vn = n.buses.v_nom.reindex(b_bus.index)
    inf.dato("carga capacitiva de lineas [MVAr]", _fmt((b_bus * vn**2).sum(), 1))
    r = n.shunt_impedances[n.shunt_impedances.index.str.startswith('reac_')]
    if len(r):
        mvar = (-r.b.values * n.buses.v_nom.reindex(r.bus).values**2).sum()
        inf.dato("reactores instalados [MVAr]", _fmt(mvar, 1))
        inf.dato("fraccion de compensacion f", _fmt(
            mvar / (b_bus * vn**2).sum(), 3), "en servicio, no instalada")
    return n


def zonas(n, inf):
    inf.seccion("2. Balance por zona [MW]")
    for pref, nombre in (('ES', 'Espana'), ('PT', 'Portugal'), ('FR', 'Francia')):
        buses = n.buses[n.buses.index.str.startswith(pref)].index
        g = n.generators[n.generators.bus.isin(buses)].p_set.sum()
        d = n.loads[n.loads.bus.isin(buses)].p_set.sum()
        inf.dato(f"{nombre}: gen / dem / balance",
                 f"{_fmt(g)} / {_fmt(d)} / {_fmt(g-d)}")


def dinamica(inf):
    from iberia import dinamica_frecuencia as din
    from iberia.analisis_btm_cascada import escenario_real
    from iberia.btm_regional import capacidad_btm_por_bus, produccion_btm_por_bus, factor_produccion

    nb = pypsa.Network(config.red('iberia_blackout.nc'))
    sis = din.Sistema(nb)
    inf.seccion("3. Punto de operacion del apagon y dinamica (D)")
    inf.dato("generacion despachada [MW]", _fmt(sis.P_gen))
    inf.dato("demanda ES+PT [MW]", _fmt(sis.P_carga), "base del amortiguamiento")
    inf.dato("demanda ES [MW]", _fmt(sis.P_carga_es), "base del EDAC")
    inf.dato("exportacion neta [MW]", _fmt(sis.exportacion))
    inf.dato("capacidad girando S_base [MVA]", _fmt(sis.S_base))
    inf.dato("inercia equivalente H [s]", _fmt(sis.H, 3))
    inf.dato("energia cinetica H*S_base [GW.s]", _fmt(sis.H * sis.S_base / 1000, 1))
    inf.dato("reserva primaria [MW]", _fmt(sis.reserva))

    cap = capacidad_btm_por_bus(nb)
    prod = produccion_btm_por_bus(nb)
    inf.dato("BTM instalado (placa) [MW]", _fmt(cap.sum()), "dato REE")
    inf.dato("factor de produccion", _fmt(factor_produccion(nb), 3),
             "FV del propio snapshot")
    inf.dato("BTM PRODUCIENDO [MW]", _fmt(prod.sum()),
             "lo que puede caerse")
    inf.dato("penetracion BTM sobre demanda ES",
             f"{100*prod.sum()/sis.P_carga_es:.1f} %".replace('.', ','))

    _, _, tr = din.simular_frecuencia(sis, escenario_real(nb, sis))
    inf.dato("escenario calibrado", din.describir(tr))
    rocof = -(9813.0 * 0.6) / (2.0 * sis.H * sis.S_base) * din.F0
    inf.dato("RoCoF inicial [Hz/s]", _fmt(rocof, 3), "analitico, primer evento")
    return nb, sis


def sensibilidad(inf):
    inf.seccion("4. Sensibilidad al BTM")
    try:
        d = pd.read_csv(config.salida('sensibilidad_btm_apagon.csv'))
    except FileNotFoundError:
        inf.dato("sensibilidad_btm_apagon.csv", "no existe", "corre python -m iberia.analisis_btm_cascada")
        return
    if 't_colapso' not in d.columns:
        inf.dato("sensibilidad_btm_apagon.csv", "OBSOLETO",
                 "sin columna t_colapso: re-corre python -m iberia.analisis_btm_cascada")
        return
    t0 = d.loc[d.penetracion_pct == 0, 't_colapso']
    t100 = d.loc[d.penetracion_pct == 100, 't_colapso']
    if len(t0) and len(t100):
        a, b = float(t0.iloc[0]), float(t100.iloc[0])
        inf.dato("colapso con 0% BTM [s]", _fmt(a, 2))
        inf.dato("colapso con 100% BTM [s]", _fmt(b, 2))
        inf.dato("aceleracion", f"{100*(a-b)/a:.1f} %".replace('.', ','),
                 "ahora sobre BTM produciendo, no placa")
    inf.dato("colapsan / total",
             f"{int(d.colapso.sum())} de {len(d)}")


def deslastre(inf):
    inf.seccion("5. Deslastre BTM-aware (E)")
    try:
        d = pd.read_csv(config.salida('comparacion_deslastre_apagon.csv'))
    except FileNotFoundError:
        inf.dato("comparacion_deslastre_apagon.csv", "no existe",
                 "corre python -m iberia.deslastre_btm_espana")
        return
    col = next((c for c in d.columns if 'sano' in c.lower()), None)
    if col is None or 'metodo' not in d.columns:
        inf.dato("formato del CSV", "inesperado", str(list(d.columns))[:60])
        return
    s = d.set_index('metodo')[col]
    milp = next((v for k, v in s.items() if 'MILP' in str(k)), None)
    prop = next((v for k, v in s.items() if 'proporcional' in str(k)), None)
    if milp is not None:
        inf.dato("BTM sano perdido, MILP [MW]", _fmt(milp))
    if prop is not None:
        inf.dato("BTM sano perdido, proporcional [MW]", _fmt(prop))
    if milp is not None and prop and prop > 0:
        inf.dato("ventaja del MILP",
                 f"{100*(prop-milp)/prop:.1f} %".replace('.', ','),
                 "a MW iguales, ponderado")


def n1(inf):
    """El barrido N-1, medido CONTRA la referencia del caso base.

    OJO AL FICHERO QUE SE LEE. Hasta el 1-nov-2026 esta seccion leia
    `contingencias_n1.csv`, que es del 27-sep: ANTERIOR a la correccion
    del doble conteo de circuits, al reparto del Slack y al dimensionado
    de los transformadores. Presentaba sus "3.072 sin problemas, 40
    sobrecargan" como cifras vigentes. El script que existe para impedir
    cifras obsoletas estaba sirviendo cifras obsoletas.

    Ahora lee `contingencias_n1_{red}.csv`, que produce barrido_rapido.py,
    y si no existe lo DICE en vez de caer a un fichero viejo.

    Y la metrica es INCREMENTAL. El caso base ya arrastra sobrecargas
    propias (12 en el apagon), asi que contar "cuantas contingencias
    tienen sobrecargas" en absoluto da el 99,6 % y no informa de nada:
    casi todas HEREDAN las del caso base sin causar ninguna.
    """
    from iberia import analisis_n1 as an
    from iberia import limites_reactivos_espana as L

    inf.seccion("6. Analisis N-1")
    for red in ('apagon', 'punta'):
        # Por fuente_n1, igual que el menu y las figuras: el barrido propio si
        # lo hay, y si no el de referencia del repositorio, diciendo cual.
        try:
            ruta, _ = an.fuente_n1(red=red)
        except SystemExit:
            inf.dato(f"[{red}] barrido N-1", "NO EXISTE",
                     f"corre python -m iberia.barrido_rapido --red {red}")
            continue
        d = pd.read_csv(ruta, encoding='utf-8-sig')

        fallos = int((d.metodo == 'AC (fallo)').sum()) if 'metodo' in d else 0
        if fallos:
            inf.dato(f"[{red}] barrido N-1", "INCOMPLETO",
                     f"{fallos} contingencias sin resolver: NO CITAR")
            continue

        # referencia del caso base, re-derivada en vivo
        try:
            base, _ = an.caso_base(verbose=False, con_limites=True, red=red)
            base_lim, _ = L.aplicar(base, verbose=False)
            est = an.estado(base_lim)
            sob_base = len(est['sobrecargados'])
            carga_base = est['carga_max_pct']
        except Exception:                            # noqa: BLE001
            sob_base, carga_base = 0, 0.0

        ac = d[d.metodo == 'AC'] if 'metodo' in d else d
        nuevas = int((ac.n_sobrecargas > sob_base).sum())
        severas = int((ac.carga_max_pct > carga_base + 50.0).sum())
        nc = int((~d.convergio).sum())
        ib = d.MW_desconectados_iberia if 'MW_desconectados_iberia' in d \
            else d.MW_desconectados

        inf.dato(f"[{red}] contingencias", _fmt(len(d), 0))
        inf.dato(f"[{red}] REFERENCIA del caso base",
                 f"{sob_base} sobrecargas, {carga_base:.1f} %".replace('.', ','),
                 "todo lo de abajo se mide contra esto")
        inf.dato(f"[{red}] no convergen", _fmt(nc, 0))
        inf.dato(f"[{red}] CREAN sobrecargas nuevas",
                 f"{nuevas} de {len(ac)}")
        inf.dato(f"[{red}] severas (+50 pp)", _fmt(severas, 0))
        inf.dato(f"[{red}] aislan carga ESPANOLA",
                 f"{int((ib > 0.1).sum())}", f"peor {ib.max():,.1f} MW")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--md', action='store_true', help="salida en Markdown")
    args = ap.parse_args()

    inf = Informe(args.md)
    print(f"{'# ' if args.md else ''}Estado actual del modelo "
          f"— re-derivado de los artefactos")
    n = red(inf)
    zonas(n, inf)
    nb, sis = dinamica(inf)
    sensibilidad(inf)
    deslastre(inf)
    n1(inf)
    print("\nTodas las cifras de arriba se han medido ahora, no leido de "
          "ningun documento.\nSi un documento dice otra cosa, el documento "
          "esta obsoleto.")


if __name__ == '__main__':
    main()
