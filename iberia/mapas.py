"""Los mapas del modelo: la red, el BTM y la cargabilidad de cada punto.

    python -m iberia.mapas red                  la red por nivel de tension
    python -m iberia.mapas btm                  donde esta el autoconsumo
    python -m iberia.mapas carga --red apagon   cargabilidad del caso base
    python -m iberia.mapas todos                los cuatro

Se escriben en resultados/mapas/ como PNG. El contorno de la peninsula sale
de data/fuentes/contorno_iberia.geojson (Natural Earth, dominio publico), de
modo que los mapas se dibujan SIN internet y sin dependencias cartograficas.

El de cargabilidad resuelve antes el caso base del punto con los limites de
reactivo: alrededor de 1 min en cada punto de operacion.
"""
import argparse
import os
import sys
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from iberia import config

# Estilo y mapas copiados de JUANCHO ESPAÑA/informe/figuras.py (7-nov-2026):
# mismo aspecto que las figuras del informe.
AZUL = 'tab:blue'
NARANJA = 'tab:orange'
VERDE = 'tab:green'
ROJO = 'tab:red'
GRIS = 'tab:gray'
GRIS_SUAVE = '#d0d0d0'
MORADO = 'tab:purple'
AMARILLO = '#f2c200'

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['DejaVu Sans'],
    'mathtext.fontset': 'dejavusans',
    'font.size': 7.5, 'axes.titlesize': 7.5, 'axes.labelsize': 7.5,
    'legend.fontsize': 6.8, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
    'axes.spines.top': True, 'axes.spines.right': True,
    'axes.edgecolor': 'black', 'axes.linewidth': 0.8,
    'axes.grid': True, 'grid.color': '#b0b0b0', 'grid.linewidth': 0.4,
    'grid.alpha': 0.5, 'axes.axisbelow': True,
    'xtick.direction': 'out', 'ytick.direction': 'out',
    'legend.frameon': True, 'legend.framealpha': 0.9,
    'legend.edgecolor': '#cccccc', 'legend.fancybox': True,
    'figure.dpi': 120,
    # NO se usa savefig.bbox='tight': recorta el lienzo al contenido, el
    # fichero sale mas estrecho que el figsize, y el width=\textwidth lo
    # estira en esa proporcion. Cada figura acabaria con un cuerpo de
    # letra distinto. Con constrained el lienzo mide lo que dice figsize.
    'figure.constrained_layout.use': True,
    'figure.constrained_layout.h_pad': 0.02,
    'figure.constrained_layout.w_pad': 0.02,
})


def guardar(fig, nombre):
    ruta = config.mapa(nombre + '.png')
    fig.savefig(ruta, dpi=200)
    plt.close(fig)
    print('  %-24s -> %s' % (nombre, os.path.relpath(ruta, config.RAIZ)))


def coma(x, dec=1):
    """Coma decimal."""
    return ('%.*f' % (dec, x)).replace('.', ',')


_CACHE_RED = {}
_CACHE_BASE = {}


def _red(cual):
    """La red de un punto de operacion, leida una sola vez por corrida."""
    if cual not in _CACHE_RED:
        import pypsa
        _CACHE_RED[cual] = pypsa.Network(config.red_de(cual))
    return _CACHE_RED[cual]


def _caso_base(red):
    """Caso base resuelto CON los limites de reactivo aplicados (cacheado)."""
    if red not in _CACHE_BASE:
        from iberia import analisis_n1 as an
        from iberia import limites_reactivos_espana as L
        base, _ = an.caso_base(verbose=False, con_limites=True, red=red)
        _CACHE_BASE[red] = L.aplicar(base, verbose=False)
    return _CACHE_BASE[red]


def _contorno():
    """Siluetas de Iberia y vecinos. data/fuentes/contorno_iberia.geojson

    Natural Earth 110m, dominio publico, 7 KB. No se usa cartopy ni
    contextily a proposito: el primero es una dependencia pesada y el
    segundo descarga teselas (y produce un mapa raster, no vectorial).
    """
    import json
    ruta = config.dato('contorno_iberia.geojson')
    if not os.path.exists(ruta):
        return []
    geo = json.load(open(ruta, encoding='utf-8'))

    def anillos(g):
        if g.get('type') == 'Polygon':
            return [g['coordinates'][0]]
        if g.get('type') == 'MultiPolygon':
            return [p[0] for p in g['coordinates']]
        return []

    out = []
    for feat in geo.get('features', []):
        nom = feat.get('properties', {}).get('name')
        for a in anillos(feat.get('geometry', {})):
            out.append((nom, [p[0] for p in a], [p[1] for p in a]))
    return out


def _fondo(ax, xlim, ylim):
    """Contorno de Iberia y vecinos, con el mar por debajo."""
    ax.set_facecolor('#eaf0f5')          # el mar
    for nom, xs, ys in _contorno():
        es_ib = nom in ('Spain', 'Portugal')
        ax.fill(xs, ys, facecolor='#fbfbf9' if es_ib else '#f0efec',
                edgecolor='#9aa5b1' if es_ib else '#c8c8c8',
                linewidth=0.7 if es_ib else 0.4, zorder=0)
    ax.set_aspect('equal')
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    _marco_geografico(ax)


def _marco_geografico(ax):
    """Marco con coordenadas en los CUATRO lados, como un mapa clasico.

    Longitud abajo y arriba, latitud a izquierda y derecha (los dos
    laterales repiten la misma escala: es un marco, no un segundo eje).
    """
    def lon(v, _p):
        v = round(v, 6)
        return '0°' if v == 0 else '%s° %s' % (coma(abs(v), 0), 'O' if v < 0 else 'E')

    def lat(v, _p):
        return '%s° N' % coma(v, 0)

    ax.grid(False)
    ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(2))
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(2))
    ax.xaxis.set_major_formatter(FuncFormatter(lon))
    ax.yaxis.set_major_formatter(FuncFormatter(lat))
    ax.tick_params(top=True, bottom=True, left=True, right=True,
                   labeltop=True, labelbottom=True, labelleft=True,
                   labelright=True, labelsize=6.5)
    for lado in ax.spines.values():
        lado.set_visible(True); lado.set_linewidth(0.8)


# Encuadre: Iberia entera mas el trozo de Francia donde estan sus cuatro
# nudos agregados. Ajustarlo a los datos recortaria la costa y dejaria
# una silueta que no se reconoce.
ENCUADRE_X = (-10.0, 4.4)
ENCUADRE_Y = (35.8, 44.2)


def fig_mapa_red():
    """Trazado de la red iberica sobre el contorno de la peninsula.

    Se dibuja desde la red del escenario del apagon, no desde el CSV de
    lineas: asi lo que aparece es exactamente lo que el modelo tiene
    -1.225 barras, 2.156 lineas y 179 transformadores- y no el registro
    del que se partio.

    Los buses de Francia y Portugal se dibujan como cuadrados huecos y
    se rotulan como AGREGADO DE PAIS, no como barras del sistema: son
    cuatro nudos ficticios por pais, y confundirlos con nudos reales es
    el origen de media docena de artefactos de este proyecto (los
    \SI{14570}{MW} de carga aislada, el Slack que saltaba a Francia, las
    perdidas infladas).

    La leyenda va DENTRO, en la esquina inferior derecha (el Mediterraneo
    al sur de Baleares, que no tiene red). Fuera dejaba un marco blanco
    que descuadraba la figura.
    """
    n = _red('apagon')
    b = n.buses
    fig, ax = plt.subplots(figsize=(6.30, 3.75))
    _fondo(ax, ENCUADRE_X, ENCUADRE_Y)

    # Convencion de colores (7-nov-2026): 400 kV en AZUL, la malla de
    # 220 y 132 kV en ROJO e interconexiones en AMARILLO. Antes los tres
    # niveles iban en tonos de un mismo azul y no se distinguian.
    from matplotlib.collections import LineCollection
    niveles = [((132.0, 220.0), ROJO, 0.40, 2, 'Línea de 220 y 132 kV'),
               ((400.0,), AZUL, 0.85, 3, 'Línea de 400 kV')]
    v0 = b.v_nom.reindex(n.lines.bus0).values
    p0 = n.lines.bus0.str[:2]; p1 = n.lines.bus1.str[:2]
    interna = (p0 == p1).values
    for vs, color, lw, z, etq in niveles:
        en_nivel = np.zeros(len(v0), dtype=bool)
        for v in vs:
            en_nivel |= np.isclose(v0, v)
        sel = n.lines[en_nivel & interna]
        segs = [[(b.at[l.bus0, 'x'], b.at[l.bus0, 'y']),
                 (b.at[l.bus1, 'x'], b.at[l.bus1, 'y'])]
                for _, l in sel.iterrows()]
        ax.add_collection(LineCollection(
            segs, colors=color, linewidths=lw, zorder=z,
            capstyle='round', label=etq))

    cruz = n.lines[~interna]
    segs = [[(b.at[l.bus0, 'x'], b.at[l.bus0, 'y']),
             (b.at[l.bus1, 'x'], b.at[l.bus1, 'y'])]
            for _, l in cruz.iterrows()]
    ax.add_collection(LineCollection(
        segs, colors=AMARILLO, linewidths=1.8, zorder=4, capstyle='round',
        label='Interconexión internacional'))

    es = b[b.index.str.startswith('ES')]
    pt = b[b.index.str.startswith('PT')]
    fr = b[b.index.str.startswith('FR')]
    # Las barras espanolas se dibujan pero NO van en la leyenda.
    ax.scatter(es.x, es.y, s=1.2, color='#333333', zorder=5, linewidths=0)
    ax.scatter(pt.x, pt.y, s=30, marker='s', facecolor='white',
               edgecolor=VERDE, lw=1.1, zorder=6,
               label='Agregado de Portugal')
    ax.scatter(fr.x, fr.y, s=30, marker='s', facecolor='white',
               edgecolor=MORADO, lw=1.1, zorder=6,
               label='Agregado de Francia')

    ax.legend(loc='lower right', fontsize=6.5)
    guardar(fig, 'mapa_red')


def fig_mapa_btm():
    """Donde esta el autoconsumo, sobre el mapa.

    Fuente: btm_regional.capacidad_btm_por_bus() sobre iberia_blackout.nc.
    El area del circulo es proporcional a los MW del bus, no el radio:
    con el radio, un bus de 250 MW parece 25 veces uno de 10 cuando solo
    es 25 veces en area.
    """
    from iberia.btm_regional import capacidad_btm_por_bus
    n = _red('apagon')
    cap = capacidad_btm_por_bus(n)
    cap = cap[cap > 0]
    b = n.buses.loc[cap.index]

    fig, ax = plt.subplots(figsize=(6.30, 3.75))
    _fondo(ax, ENCUADRE_X, ENCUADRE_Y)
    for _, l in n.lines.iterrows():
        ax.plot([n.buses.at[l.bus0, 'x'], n.buses.at[l.bus1, 'x']],
                [n.buses.at[l.bus0, 'y'], n.buses.at[l.bus1, 'y']],
                color='#d7dde3', lw=0.25, zorder=1)

    # Color por banda de potencia (el tamano sigue siendo proporcional
    # al area): con un solo naranja las barras pequenas y las grandes se
    # confundian. En la leyenda, rectangulos de color, no circulos.
    from matplotlib.patches import Patch
    bandas = [(0.0, 1.0, '#fed976', '< 1 MW'),
              (1.0, 10.0, '#fd8d3c', '1 – 10 MW'),
              (10.0, 50.0, '#e31a1c', '10 – 50 MW'),
              (50.0, float('inf'), '#800026', '> 50 MW')]
    manejadores = []
    for lo, hi, color, etq in bandas:
        sel = cap[(cap >= lo) & (cap < hi)]
        if len(sel):
            ax.scatter(b.loc[sel.index, 'x'], b.loc[sel.index, 'y'],
                       s=np.maximum(sel.values * 0.9, 2.0), color=color,
                       alpha=0.8, linewidths=0.2, edgecolor='#555555',
                       zorder=4 + bandas.index((lo, hi, color, etq)))
        manejadores.append(Patch(facecolor=color, edgecolor='#555555',
                                 lw=0.4, label=etq))
    ax.legend(handles=manejadores, loc='lower right', fontsize=6.5,
              title='BTM por barra', title_fontsize=6.8)
    guardar(fig, 'mapa_btm')


# Bandas de cargabilidad. Los cuatro tonos conservan la semantica
# -verde tranquilo, rojo alarma- y el grosor crece con la banda, de modo
# que el color nunca carga solo el dato.
BANDAS_CARGA = [
    (0.0, 50.0, '#2ca02c', 0.30, '< 50 %'),
    (50.0, 75.0, '#e6b800', 0.60, '50 – 75 %'),
    (75.0, 100.0, '#ff7f0e', 1.00, '75 – 100 %'),
    (100.0, float('inf'), '#d62728', 1.70, '> 100 %'),
]


def _mapa_cargabilidad(red):
    """Trazado de la red con las ramas coloreadas por banda de carga.

    Gemela de `mapa_carga_{punto}` del STN. Se dibuja de la banda mas
    baja a la mas alta para que los corredores exigidos queden encima y
    no los tape una linea descargada.
    """
    from matplotlib.collections import LineCollection
    from iberia import analisis_n1 as an
    nl, _ = _caso_base(red)
    b = nl.buses
    pct = an.cargabilidad(nl)

    fig, ax = plt.subplots(figsize=(6.30, 3.75))
    _fondo(ax, ENCUADRE_X, ENCUADRE_Y)
    for lo, hi, color, lw, etq in BANDAS_CARGA:
        sel = [k for k in nl.lines.index
               if lo <= float(pct.get(k, 0.0)) < hi]
        if not sel:
            continue          # la banda sigue en la leyenda (ver abajo)
        segs = [[(b.at[nl.lines.at[k, 'bus0'], 'x'],
                  b.at[nl.lines.at[k, 'bus0'], 'y']),
                 (b.at[nl.lines.at[k, 'bus1'], 'x'],
                  b.at[nl.lines.at[k, 'bus1'], 'y'])] for k in sel]
        ax.add_collection(LineCollection(
            segs, colors=color, linewidths=lw, capstyle='round',
            zorder=2 + BANDAS_CARGA.index((lo, hi, color, lw, etq)),
            ))
    # Las CUATRO bandas siempre en la leyenda, aunque alguna este vacia
    # (el apagon no tiene ramas > 100 %): asi los mapas de los escenarios
    # se leen con la misma clave.
    from matplotlib.lines import Line2D
    manejadores = [Line2D([], [], color=c, lw=max(w, 0.8) * 1.4, label=e)
                   for _lo, _hi, c, w, e in BANDAS_CARGA]
    ax.legend(handles=manejadores, loc='lower right', fontsize=6.5,
              title='Cargabilidad', title_fontsize=6.8)
    guardar(fig, 'mapa_carga_%s' % red)


MAPAS = {
    'red': lambda red: fig_mapa_red(),
    'btm': lambda red: fig_mapa_btm(),
    'carga': lambda red: _mapa_cargabilidad(red),
}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mapa', choices=list(MAPAS) + ['todos'])
    config.anadir_arg_red(ap)
    args = ap.parse_args()
    if args.mapa == 'carga' and args.red not in ('apagon', 'punta'):
        raise SystemExit("el mapa de carga existe para 'apagon' y 'punta'")
    elegidos = ['red', 'btm', 'carga'] if args.mapa == 'todos' else [args.mapa]
    for m in elegidos:
        MAPAS[m](args.red)
    return 0


if __name__ == '__main__':
    sys.exit(main())
