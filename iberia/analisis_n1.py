"""Analisis de contingencias N-1 sobre el modelo iberico (Espana+Portugal+Francia).

Simula la salida de cada linea, transformador y generador de iberia_scenario.nc y
evalua el resultado contra tres criterios: convergencia del flujo AC completo,
carga desconectada (si la contingencia separa la red en islas), y sobrecargas o
tensiones fuera de rango en la parte que sigue conectada.

Criterio de sobrecarga: un solo umbral al 100% de s_nom (esta red, a diferencia
del modelo del STN, no trae limite de emergencia tipo PARATEC). Las violaciones
se reportan en absoluto, no relativas al caso base: el caso base de esta red no
tiene ninguna violacion previa (verificado), asi que la distincion no aporta.

Uso:
    python analisis_n1.py                    # N-1 completo (3.277 elementos)
    python analisis_n1.py --tipo linea        # solo lineas
    python analisis_n1.py --top 30 --csv salida.csv
"""
import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

# PyPSA emite un INFO por cada flujo que resuelve. El barrido con limites
# de reactivo resuelve ~14 por contingencia (el lazo PV->PQ), asi que las
# 3.277 contingencias generan unas 46.000 lineas de ruido que ahogan el
# progreso y engordan el log a cientos de MB en una corrida de ~17 h.
logging.getLogger('pypsa').setLevel(logging.WARNING)
warnings.filterwarnings('ignore')

import networkx as nx
import numpy as np
import pandas as pd

from iberia import config
import pypsa


# Potencia minima para que un generador REGULE tension (bus PV). Por
# debajo queda como inyeccion PQ, que es como un operador de transporte
# modela la generacion embebida. Justificacion del mecanismo en
# preparar_para_flujo_ac().
#
# DE 1,0 A 25,0 MW (1-nov-2026). El valor de 1 MW se introdujo al
# corregir el caso G0946 -0,050 MW regulando un bus de 400 kV- pero se
# quedo tan bajo que no excluia practicamente a nadie: maquinas de 5 y
# 10 MW seguian sosteniendo la tension de nudos de 220 y 400 kV.
#
# 25 MW se elige por el CRITERIO FISICO -por debajo de ese orden una
# maquina no sostiene la tension de un nudo de transporte- y se comprueba
# que no rompe nada. NO se elige por hacer converger la punta, que es lo
# que no hace. Medido con calibrar_umbral_pv.py:
#
#   umbral   apagon                     punta
#            fuera   carga_max   sob    fuera   exceso MVAr   estabiliza
#    1 MW      0      121,8 %     12      28       5.460,7       NO
#   10 MW      0      121,8 %     12      20       5.111,5       NO
#   25 MW      0      121,7 %     12      16       4.747,3       NO   <- adoptado
#   50 MW      0      121,8 %     12     -- el flujo base NO converge --
#  100 MW      0      121,6 %     12     -- el flujo base NO converge --
#
# LO QUE ESTO **NO** ARREGLA, Y HAY QUE DECIRLO. El defecto que motivo el
# barrido era que en la PUNTA el lazo de limites de reactivo se detiene
# en la iteracion 2 de 60 dejando 28 generadores fuera de su curva. Con
# 25 MW siguen siendo 16, con 4.747 MVAr de exceso, y **el lazo sigue
# sin estabilizar**. La hipotesis de que las maquinas pequenas causaban
# la no-convergencia es FALSA: contribuyen, pero el lazo se rinde igual.
#
# Y EL HALLAZGO DE FONDO, que vale mas que el ajuste: a partir de 50 MW
# el caso base de la PUNTA **ni siquiera converge**. Es decir, ese
# escenario DEPENDE de que maquinas por debajo de 50 MW regulen tension
# en nudos de transporte. Un sistema de 40 GW no deberia necesitarlo.
# Apunta a que el problema no es el umbral sino el DESPACHO de la punta,
# que es un escenario derivado y no validado (se construyo escalando
# tecnologias, sin orden de merito), y que deja demasiada poca
# generacion grande regulando.
#
# El APAGON es insensible al umbral: cero fuera de curva en los cinco
# valores y cifras que se mueven en la cuarta cifra significativa. Eso
# confirma que sus resultados de N-1 no estaban contaminados por esto.
P_NOM_MIN_PV = 25.0   # MW

# Nombres de los dos barridos posibles. `contingencias_n1.csv` esta
# RESERVADO para el barrido CON limites de reactivo, que es el unico
# fisicamente valido; el de sin limites lleva sufijo explicito.
CSV_CON_LIMITES = 'contingencias_n1.csv'
CSV_SIN_LIMITES = 'contingencias_n1_sin_limites.csv'


def fuente_n1(red=None, preferir_con_limites=True):
    """Devuelve (ruta, etiqueta) del barrido N-1 a usar, y ANUNCIA cual.

    Existe porque los scripts que consumen el barrido leian
    'contingencias_n1.csv' a pelo. Cuando ese fichero quedaba de una
    configuracion anterior del modelo, seguian funcionando sin
    protestar y producian graficos y muestras de datos obsoletos - paso
    de verdad: una corrida completa del menu dio OK mientras visualizaba
    un barrido de otra red.

    LA GUARDA SE QUEDO CORTA, Y DEL MISMO MODO (corregido el 2-nov-2026).
    Se escribio cuando solo habia dos barridos posibles y los dos tenian
    nombre fijo. Al llegar `barrido_rapido.py`, que escribe
    `contingencias_n1_<escenario>.csv`, esos ficheros nuevos NO entraron
    en la lista de candidatos: la funcion seguia prefiriendo
    `contingencias_n1.csv`, que en esta copia era del 27 de septiembre.
    Es decir, la propia funcion escrita para impedir que se dibujaran
    barridos obsoletos estaba sirviendo uno de hace seis semanas.

    Ahora los barridos POR ESCENARIO van primero, porque son los que
    produce el camino vigente. `red` elige cual; sin `red` se cogen por
    fecha, el mas reciente. Los dos nombres antiguos quedan al final y se
    anuncian como HEREDADOS, para que quien los vea sepa que no salen del
    camino actual."""
    import os
    import time

    candidatos = []
    escenarios = [red] if red else list(config.ESCENARIOS)
    # 1. Un barrido PROPIO, corrido en esta copia del modelo: el mas reciente.
    for e in escenarios:
        nombre = f'contingencias_n1_{e}.csv'
        ruta = config.salida(nombre)
        if os.path.exists(ruta):
            candidatos.append((os.path.getmtime(ruta), nombre, ruta,
                               f'barrido de {e}, con limites de Q'))
    candidatos.sort(reverse=True)

    # 2. Si no hay, el de REFERENCIA que trae el repositorio. Es el mismo
    # calculo, hecho una vez sobre estas mismas redes; existe para que el
    # ranking y las figuras del N-1 funcionen nada mas descargar, sin
    # esperar los 34 min (apagon) o 138 min (punta) de un barrido completo.
    if not candidatos:
        for e in escenarios:
            nombre = f'contingencias_n1_{e}.csv'
            ruta = str(config.DIR_REFERENCIA / nombre)
            if os.path.exists(ruta):
                candidatos.append((0.0, nombre, ruta,
                                   f'REFERENCIA del repositorio, {e}'))

    if not candidatos:
        raise SystemExit(
            "No hay ningun barrido N-1 para este punto de operacion.\n"
            "  Corre 'python -m iberia.barrido_rapido --red <punto>', que\n"
            "  lo escribe en resultados/contingencias_n1_<punto>.csv.")

    _, nombre, ruta, etiqueta = candidatos[0]
    fecha = time.strftime('%Y-%m-%d %H:%M',
                          time.localtime(os.path.getmtime(ruta)))
    print(f"  [fuente N-1] {nombre} ({etiqueta}, del {fecha})")
    return ruta, etiqueta


V_MIN, V_MAX = 0.90, 1.10
CARGA_MAX_PCT = 100.0
ATRIBUTO = {'Line': 'lines', 'Transformer': 'transformers', 'Generator': 'generators',
            'Load': 'loads', 'Bus': 'buses'}


def _tabla(n, tipo):
    return getattr(n, ATRIBUTO[tipo])


def preparar_para_flujo_ac(n):
    """Configura buses PV (generadores sincronos) y Slack para que el flujo AC
    converja.

    Sin esto, TODOS los generadores quedan PQ (fijos en P y Q) y el flujo de
    potencia completo (Newton-Raphson) no converge: un solo bus (el Slack) no
    puede sostener el reactivo de una red de 1.225 buses y 2.156 lineas -
    confirmado empiricamente ("Matrix is exactly singular"). Se llama de nuevo
    en cada contingencia (no solo en el caso base) porque el generador Slack
    puede ser justo el elemento que se esta sacando de servicio.

    Devuelve el id del generador designado Slack, o None si no queda ningun
    generador sincrono (H>0) tras la contingencia - en ese caso el flujo AC no
    se puede resolver y el llamador debe tratarlo como no-convergencia.
    """
    sincronos = n.generators[n.generators.H > 0]
    if not len(sincronos):
        return None

    # Solo las maquinas con tamano suficiente REGULAN tension. Las demas
    # quedan como inyeccion PQ, que es como un operador de transporte
    # modela la generacion embebida: entrega potencia a factor de potencia
    # fijo y no sostiene la tension de un nudo de 220/400 kV.
    #
    # Sin este filtro el lazo PV->PQ de limites_reactivos_espana.py entra
    # en CICLO LIMITE y agota sus 60 iteraciones. El caso que lo provoca:
    # G0946, un Run_of_river de 0,050 MW (50 kW) que es el unico sincrono
    # de ES00641, un bus de 400 kV. PyPSA le atribuye el reactivo entero
    # del nudo (-67 MVAr) contra una curva de +-0,05 MVAr; se le fija en
    # su limite, la tension cae por debajo de la consigna, la regla de
    # retorno lo devuelve a PV y el ciclo se repite indefinidamente.
    #
    # Medido sobre el caso base (el resultado fisico NO cambia, solo el
    # coste, lo que confirma que estas maquinas no sostenian nada):
    #   umbral  buses PV  iteraciones  tiempo   v_min   v_max  carga_max
    #    0 MW      240     60 (agota)   182 s  0,9197  1,0793    102,0%
    #    1 MW      235          7        21 s  0,9202  1,0793    102,0%
    #    5 MW      220          7        21 s  0,9202  1,0794    102,0%
    #   20 MW      197          7        22 s  0,9204  1,0806    102,0%
    #
    # Se adopta 1 MW: el resultado es insensible entre 1 y 20 MW, asi que
    # se elige el umbral MINIMO que resuelve el defecto, para no quitar
    # soporte de tension sin necesidad. Un operador real usaria un umbral
    # mas alto; aqui no haria diferencia. Afecta a 5 de los 240 sincronos.
    #
    # Justificacion fisica del orden de magnitud: con cos phi_nom = 0,90,
    # una maquina de 1 MW tiene S = 1,11 MVA y Q_max ~ 0,48 MVAr. Un nudo
    # de 400 kV necesita decenas de MVAr. Por debajo de ahi, llamarla
    # "reguladora de tension" es una ficcion del modelo.
    elegibles = sincronos[sincronos.p_nom >= P_NOM_MIN_PV]
    if not len(elegibles):
        # Ninguna maquina alcanza el umbral: antes que no resolver, se
        # vuelve al criterio antiguo. Puede pasar en una isla pequena
        # tras una contingencia severa.
        elegibles = sincronos

    # El Slack DESIGNADO manda; el mayor sincrono es solo el sustituto.
    #
    # add_neighbors_v2.py elige y persiste G0031 (hidraulica de embalse
    # espanola, 1.452 MW) con una justificacion explicita: es flexible y
    # esta en el sistema que se estudia. Esta funcion lo pisaba con
    # `elegibles.p_nom.idxmax()`, que devuelve FR_Nuclear_FR00742, un
    # AGREGADO FRANCES de 10.255 MW - uno de los cuatro buses ficticios
    # que representan a toda Francia.
    #
    # Por que importa, y no es un detalle de implementacion: el Slack
    # absorbe TODO el desbalance de cada contingencia, sin limite de
    # capacidad ni de rampa. Con un agregado de 10 GW al otro lado de la
    # frontera haciendo ese papel, perder cualquier generador espanol
    # -el mayor despacha 303,6 MW- es benigno POR CONSTRUCCION. El
    # "0 de 942 generadores causan problema" que el proyecto publicaba
    # no medi­a la robustez de la red espanola: medi­a el tamano del
    # comodin frances.
    #
    # El `preparar_para_flujo_ac` se vuelve a llamar en cada contingencia
    # precisamente porque el Slack puede ser el elemento retirado; de ahi
    # el sustituto. Pero sustituir no es lo mismo que ignorar.
    #
    # Y EL SUSTITUTO TAMBIEN TIENE QUE SER IBERICO (corregido el
    # 1-nov-2026). Hasta ahora el sustituto salia de
    # `elegibles.p_nom.idxmax()`, el mayor de TODA la red - que es
    # justamente un agregado frances de 10.255 MW. Asi que el bug de
    # arriba seguia vivo por la puerta de atras: bastaba con que la
    # contingencia fuese el propio Slack espanol para que la referencia
    # saltara a Francia.
    #
    # Medido: al quitar G0031 (el Slack designado) el sustituto era
    # FR_Nuclear_FR00742 y el flujo NO convergia. Aparecia en el barrido
    # como "G0031 no converge", es decir un defecto del metodo disfrazado
    # de resultado.
    #
    # Ahora el sustituto se busca primero entre los generadores IBERICOS
    # (ES/PT), y solo si no hubiera ninguno se cae al global.
    designado = n.generators.index[n.generators.control == 'Slack']
    designado = [g for g in designado if g in elegibles.index]
    if designado:
        slack_id = designado[0]
    else:
        ibericos = elegibles[elegibles.bus.str.startswith(('ES', 'PT'))]
        slack_id = (ibericos.p_nom.idxmax() if len(ibericos)
                    else elegibles.p_nom.idxmax())

    n.generators['control'] = 'PQ'
    n.generators.loc[elegibles.index, 'control'] = 'PV'
    if 'v_set' not in n.generators.columns:
        n.generators['v_set'] = 1.0
    else:
        n.generators.loc[elegibles.index, 'v_set'] = 1.0
    n.generators.loc[slack_id, 'control'] = 'Slack'
    return slack_id


def _grafo(n):
    g = nx.Graph()
    g.add_nodes_from(n.buses.index)
    g.add_edges_from(zip(n.lines.bus0, n.lines.bus1))
    if len(n.transformers):
        g.add_edges_from(zip(n.transformers.bus0, n.transformers.bus1))
    return g


# Paises modelados como agregado de 4 buses ficticios. Su carga NO es
# carga del sistema que se estudia: es la condicion de contorno.
#
# PORTUGAL INCLUIDO desde el 7-nov-2026. Antes solo se excluia Francia, y
# Portugal es exactamente igual: 4 nudos de 1.200 MW, cada uno colgado de
# su interconexion. El "peor caso iberico" de 1.200,8 MW que el informe
# citaba era uno de esos nudos, no carga espanola (el peor caso espanol
# real eran 561,1 MW en el apagon). Desde entonces la columna
# `MW_desconectados_iberia` mide carga ESPANOLA: el nombre se conserva
# para no romper los CSV ni sus lectores.
PAISES_AGREGADOS_N1 = ('FR', 'PT')


def separar_islas(n):
    """Deja solo la isla principal (la que concentra mas generacion) y devuelve
    (carga perdida TOTAL, generacion perdida, numero de islas, carga perdida
    IBERICA).

    POR QUE SE SEPARA LA CARGA IBERICA DE LA AGREGADA (1-nov-2026).

    Francia son 4 buses ficticios que reparten sus ~58.000 MW de demanda a
    ~14.500 MW cada uno. Cortar la unica rama que alimenta uno aisla esa
    demanda entera, y el barrido lo reportaba como "14.570 MW
    desconectados" - la contingencia mas grave del sistema, por delante de
    cualquier otra.

    No lo es. Esa cifra no mide ninguna debilidad de la red espanola: su
    magnitud la fija la decision de modelar Francia con 4 buses. Con 8
    buses saldrian 7.250 MW; con 1, saldrian 58.000.

    Medido sobre las 181 ramas puente que aislan carga: de los 126.322 MW
    reportados, **116.000 (el 91,8 %) eran franceses**, y los producian
    solo 5 contingencias. El peor caso IBERICO real son 1.200 MW, un 4,4 %
    de la demanda espanola - una cifra creible para la perdida de un
    corredor radial.

    Es el mismo error que ya se corrigio en las perdidas de
    comparar_escenarios: mezclar el sistema estudiado con su condicion de
    contorno. `severidad()` ordena ahora por la carga IBERICA."""
    comps = list(nx.connected_components(_grafo(n)))
    if len(comps) <= 1:
        return 0.0, 0.0, 1, 0.0

    gen_por_isla = [float(n.generators[n.generators.bus.isin(c)].p_set.sum()) for c in comps]
    principal = comps[int(np.argmax(gen_por_isla))]
    fuera = [b for c in comps if c is not principal for b in c]
    if not fuera:
        return 0.0, 0.0, len(comps), 0.0

    perdidas = n.loads[n.loads.bus.isin(fuera)]
    carga_perdida = float(perdidas.p_set.sum())
    agregada = perdidas.bus.str.startswith(PAISES_AGREGADOS_N1)
    carga_iberica = float(perdidas[~agregada].p_set.sum())
    gen_perdida = float(n.generators[n.generators.bus.isin(fuera)].p_set.sum())

    for comp, col in (('Generator', 'bus'), ('Load', 'bus')):
        df = _tabla(n, comp)
        if len(df):
            quitar = df[df[col].isin(fuera)].index.tolist()
            if quitar:
                n.remove(comp, quitar)
    for comp in ('Line', 'Transformer'):
        df = _tabla(n, comp)
        if len(df):
            quitar = df[df.bus0.isin(fuera) | df.bus1.isin(fuera)].index.tolist()
            if quitar:
                n.remove(comp, quitar)
    n.remove('Bus', fuera)
    return carga_perdida, gen_perdida, len(comps), carga_iberica


def cargabilidad(n):
    """Cargabilidad de lineas y trafos en % de s_nom (esta red no tiene s_eme)."""
    out = {}
    if len(n.lines) and len(n.lines_t.p0):
        s = np.hypot(n.lines_t.p0.iloc[0], n.lines_t.q0.iloc[0])
        pct = (s / n.lines.s_nom.replace(0, np.nan) * 100).dropna()
        out.update(pct.to_dict())
    if len(n.transformers) and len(n.transformers_t.p0):
        s = np.hypot(n.transformers_t.p0.iloc[0], n.transformers_t.q0.iloc[0])
        pct = (s / n.transformers.s_nom.replace(0, np.nan) * 100).dropna()
        out.update(pct.to_dict())
    return pd.Series(out, dtype=float)


def estado(n):
    v = n.buses_t.v_mag_pu.iloc[0]
    pct = cargabilidad(n)
    return {
        'v_min': float(v.min()), 'v_max': float(v.max()),
        'v_bajas': set(v[v < V_MIN].index), 'v_altas': set(v[v > V_MAX].index),
        'carga_pct': pct,
        'carga_max_pct': float(pct.max()) if len(pct) else 0.0,
        'sobrecargados': set(pct[pct > CARGA_MAX_PCT].index),
    }


def caso_base(verbose=True, con_limites=True, red='escenario'):
    """Construye y resuelve el caso base. Unica puerta de entrada al modelo
    para el barrido de contingencias.

    `con_limites` afecta SOLO al diagnostico que se informa, no a la red
    que se devuelve: las contingencias parten siempre de la red sin
    conmutar y `simular()` aplica los limites por su cuenta. Se informa
    con limites por defecto porque el caso base SIN ellos no es un punto
    de operacion fisicamente valido - deja a los generadores produciendo
    reactivo imposible (ver el modulo limites_reactivos_espana).

    Ejemplo medido del por que: sin limites, el caso base carga L1357 al
    ~150% por reactivo que sus generadores no podrian producir, mientras
    que con limites esa misma red no tiene ninguna barra fuera de rango y
    el elemento mas cargado es otro (L0627, al 102%).

    CONSECUENCIA PRACTICA, que ha mordido ya una vez: la red que se
    devuelve y el diagnostico que se informa NO son el mismo estado.
    Calcular cargabilidad sobre la red devuelta y leer la tension del
    diagnostico mezcla dos modelos y produce un caso base incoherente -
    150% de carga junto a "0 barras fuera de rango". Quien necesite la red
    coherente debe aplicar los limites el mismo, como hace menu.py.
    """
    n = pypsa.Network(config.red_de(red))
    if verbose:
        print(f"Punto de operacion: {red} "
              f"({config.describir_escenario(red)})")
    slack_id = preparar_para_flujo_ac(n)
    if slack_id is None:
        raise RuntimeError('sin generadores sincronos en el caso base')
    resultado = n.pf()
    if not bool(resultado['converged'].iloc[0, 0]):
        raise RuntimeError('El caso base no converge; no tiene sentido analizar '
                            'contingencias sobre el.')

    if con_limites:
        from iberia import limites_reactivos_espana as L
        n_diag, info = L.aplicar(n, verbose=False)
        if not info['convergio']:
            raise RuntimeError('el caso base no converge con limites de reactivo')
        diag = estado(n_diag)
        diag['n_fuera_curva_q'] = len(info['restantes'])
        diag['n_conmutados'] = len(info['conmutados'])
    else:
        diag = estado(n)
        diag['n_fuera_curva_q'] = 0
        diag['n_conmutados'] = 0

    if verbose:
        etiqueta = "con limites de reactivo" if con_limites else "SIN limites (no fisico)"
        print(f"Caso base ({etiqueta}): {len(n.buses)} buses, {len(n.lines)} lineas, "
              f"{len(n.transformers)} trafos, {len(n.generators)} generadores")
        print(f"  Slack: {slack_id} | tension [{diag['v_min']:.4f}, "
              f"{diag['v_max']:.4f}] p.u. | cargabilidad max {diag['carga_max_pct']:.1f}%")
        if con_limites:
            print(f"  {diag['n_conmutados']} generadores conmutados a PQ, "
                  f"{diag['n_fuera_curva_q']} siguen fuera de su curva")
        if diag['v_bajas'] or diag['v_altas'] or diag['sobrecargados']:
            print(f"  AVISO: el caso base ya tiene violaciones: "
                  f"{len(diag['v_bajas'])} tension baja, {len(diag['v_altas'])} tension alta, "
                  f"{len(diag['sobrecargados'])} sobrecargas")
    return n, diag


def simular(base, tipo, nombre, con_limites=True, fijados_iniciales=None):
    """Saca de servicio un elemento y evalua el resultado. `tipo` en
    {'Line', 'Transformer', 'Generator'}.

    `con_limites=True` (POR DEFECTO) impone limites de potencia reactiva
    por generador (ver limites_reactivos_espana.py) en vez de un solo
    flujo AC con reactivo ilimitado. Es mucho mas lento - ~187 s por
    contingencia medidos sobre la red compensada, frente a ~0,8 s sin
    limites - pero es la unica forma de que el resultado sea fisicamente
    valido: sin limites los generadores sostienen su tension con MVAr que
    sus maquinas no pueden dar, y eso tanto oculta colapsos de tension
    reales como inventa sobrecargas que no existen.

    `con_limites=False` se conserva para reproducir el baseline historico
    del proyecto (sub-proyectos C a F) y para barridos exploratorios
    rapidos, pero su resultado NO debe citarse como fisico."""
    n = base.copy()
    if nombre not in _tabla(n, tipo).index:
        return None
    n.remove(tipo, nombre)

    carga_perdida, gen_perdida, n_islas, carga_iberica = separar_islas(n)
    res = {
        'tipo': tipo, 'elemento': nombre, 'islas': n_islas,
        'MW_desconectados': round(carga_perdida, 1),
        'MW_desconectados_iberia': round(carga_iberica, 1),
        'MW_gen_perdida': round(gen_perdida, 1),
    }

    sin_resultado = {'convergio': False, 'motivo': '', 'carga_max_pct': np.nan,
                      'n_sobrecargas': 0, 'v_min': np.nan, 'v_max': np.nan,
                      'n_v_bajas': 0, 'n_v_altas': 0, 'elemento_critico': '',
                      'n_fuera_curva_q': 0}

    if not len(n.buses) or not len(n.generators):
        res.update(sin_resultado, motivo='red sin generacion')
        return res

    try:
        slack_id = preparar_para_flujo_ac(n)
        if slack_id is None:
            res.update(sin_resultado, motivo='sin generadores sincronos')
            return res
        if con_limites:
            from iberia import limites_reactivos_espana as L
            n, info = L.aplicar(n, verbose=False,
                                fijados_iniciales=fijados_iniciales)
            ok = info['convergio']
        else:
            resultado = n.pf()
            ok = bool(resultado['converged'].iloc[0, 0])
    except Exception as e:                      # noqa: BLE001
        res.update(sin_resultado, motivo=type(e).__name__)
        return res

    if not ok:
        res.update(sin_resultado, motivo='no converge')
        return res

    est = estado(n)
    critico = est['carga_pct'].idxmax() if len(est['carga_pct']) else ''
    res.update({
        'convergio': True, 'motivo': '',
        'carga_max_pct': round(est['carga_max_pct'], 1),
        'n_sobrecargas': len(est['sobrecargados']),
        'elemento_critico': critico,
        'v_min': round(est['v_min'], 4), 'v_max': round(est['v_max'], 4),
        'n_v_bajas': len(est['v_bajas']), 'n_v_altas': len(est['v_altas']),
        'n_fuera_curva_q': len(info['restantes']) if con_limites else 0,
    })
    return res


def severidad(r):
    """Puntua la gravedad para poder ordenar los casos. Orden de importancia:
    no converger > dejar carga sin servicio > sobrecargar equipos > tension
    fuera de rango."""
    if not r['convergio']:
        return 1e9
    s = 0.0
    # La carga IBERICA, no la total: la agregada francesa produce cifras
    # enormes que no miden la red espanola (ver separar_islas). Se cae a
    # MW_desconectados solo si la columna no existe, para no romper la
    # lectura de CSV antiguos.
    s += r.get('MW_desconectados_iberia', r['MW_desconectados']) * 100
    s += max(r['carga_max_pct'] - 100.0, 0.0) * 50
    s += r['n_sobrecargas'] * 500
    s += (r['n_v_bajas'] + r['n_v_altas']) * 100
    return s


def elementos_de(network, tipos=('Line', 'Transformer', 'Generator')):
    """Lista de (tipo, nombre) candidatos para el barrido.

    Los generadores de Portugal y Francia (nombre con prefijo PT_/FR_, ver
    add_neighbors_v2.py) son agregados de toda la flota de un pais por
    tecnologia en 4 buses, no centrales individuales reales - sacar uno de un
    golpe no es una contingencia N-1 creible (verificado en la Tarea 1: los 6
    mas grandes ni siquiera convergen, y los otros 14 son igual de ficticios
    aunque no diverjan numericamente). Se excluyen SOLO del tipo Generator;
    las lineas/trafos de Portugal y Francia (infraestructura real) siguen en
    alcance.
    """
    out = []
    for tipo in tipos:
        for nombre in _tabla(network, tipo).index:
            if tipo == 'Generator' and nombre.startswith(('PT_', 'FR_')):
                continue
            out.append((tipo, nombre))
    return out


def barrido(base, candidatos, verbose=True, con_limites=True,
            csv_parcial=None, cada=25):
    """Simula `candidatos` y devuelve el resultado ordenado por severidad.

    `csv_parcial`: si se da una ruta, el resultado se vuelca ahi cada
    `cada` contingencias. CON LIMITES DE REACTIVO ESTO NO ES OPCIONAL: el
    barrido completo son ~17 h, y antes todo se acumulaba en memoria y se
    escribia solo al terminar. Una suspension del portatil, un tropiezo de
    la sincronizacion o un Ctrl-C a las 16 horas se llevaban las 16 horas.
    """
    if verbose:
        etiqueta = " (con limites de reactivo)" if con_limites else ""
        print(f"\nSimulando {len(candidatos)} contingencias{etiqueta}...")
        if csv_parcial:
            print(f"  guardado parcial cada {cada} en {csv_parcial.name}")
    t0 = time.time()
    filas = []
    for i, (tipo, nombre) in enumerate(candidatos, 1):
        filas.append(simular(base, tipo, nombre, con_limites=con_limites))
        if csv_parcial and (i % cada == 0 or i == len(candidatos)):
            pd.DataFrame(filas).to_csv(csv_parcial, index=False,
                                       encoding='utf-8-sig')
        if verbose and (i % cada == 0 or i == len(candidatos)):
            transcurrido = time.time() - t0
            resta = transcurrido / i * (len(candidatos) - i)
            print(f"  {i}/{len(candidatos)}  {transcurrido/60:.0f} min "
                  f"transcurridos, quedan ~{resta/3600:.1f} h", flush=True)
    d = pd.DataFrame(filas)
    d['severidad'] = d.apply(severidad, axis=1)
    return d.sort_values('severidad', ascending=False).reset_index(drop=True)


def informe(d, top=20):
    n = len(d)
    no_conv = d[~d.convergio]
    con_isla = d[d.MW_desconectados > 0.1]
    con_sobre = d[d.n_sobrecargas > 0]
    con_v = d[(d.n_v_bajas + d.n_v_altas) > 0]
    seguras = d[(d.convergio) & (d.MW_desconectados <= 0.1) &
                (d.n_sobrecargas == 0) & ((d.n_v_bajas + d.n_v_altas) == 0)]

    print("\n" + "=" * 72)
    print(f" RESULTADO: {n} contingencias simuladas")
    print("=" * 72)
    print(f"  sin problemas                    : {len(seguras):4d}  "
          f"({100*len(seguras)/max(n,1):.1f}%)")
    print(f"  el flujo no converge             : {len(no_conv):4d}")
    print(f"  dejan carga sin servicio         : {len(con_isla):4d}  "
          f"(hasta {d.MW_desconectados.max():.1f} MW)")
    print(f"  sobrecargan algun elemento       : {len(con_sobre):4d}")
    print(f"  sacan alguna tension de rango    : {len(con_v):4d}")

    if len(d[d.convergio]):
        print(f"\n  cargabilidad maxima alcanzada: {d[d.convergio].carga_max_pct.max():.1f}%")

    peores = d.head(top)
    if len(peores):
        print(f"\n  Las {len(peores)} contingencias mas severas:")
        cols = ['tipo', 'elemento', 'convergio', 'MW_desconectados',
                'carga_max_pct', 'n_sobrecargas', 'v_min', 'n_v_bajas']
        print(peores[cols].to_string(index=False))

    if len(con_sobre):
        print("\n  Elementos que mas veces quedan sobrecargados:")
        print(con_sobre.elemento_critico.value_counts().head(8).to_string())

    if 'n_fuera_curva_q' in d.columns and d.n_fuera_curva_q.sum() > 0:
        con_q = d[d.n_fuera_curva_q > 0]
        print(f"  generadores fuera de su curva de Q (tras el lazo): "
              f"{len(con_q)} contingencias con al menos uno, "
              f"maximo {d.n_fuera_curva_q.max()}")


def main():
    ap = argparse.ArgumentParser(description="Analisis N-1 sobre iberia_scenario.nc")
    ap.add_argument('--tipo', choices=['linea', 'trafo', 'generador', 'todos'],
                     default='todos')
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--csv', default=None)
    ap.add_argument('--sin-limites', action='store_true',
                    help="NO imponer limites de potencia reactiva. Reproduce "
                         "el baseline historico (sub-proyectos C-F) y es ~200x "
                         "mas rapido, pero el resultado NO es fisicamente "
                         "valido: los generadores sostienen su tension con "
                         "MVAr que sus maquinas no pueden dar")
    config.anadir_arg_red(ap, por_defecto='escenario')
    ap.add_argument('--forzar', action='store_true',
                    help="permitir un barrido completo CON limites pese a su "
                         "costo (~170 h medidas). Sin esto, el barrido "
                         "completo con limites se rechaza para no dejar "
                         "corriendo una semana por accidente")
    args = ap.parse_args()
    con_limites = not args.sin_limites

    # Guarda de costo. Los limites de reactivo cuestan ~187 s/contingencia
    # (medido sobre 10 casos con la red compensada), asi que un barrido
    # completo de 3.277 son ~170 horas. Es el comportamiento correcto
    # fisicamente, pero dejarlo como el default silencioso de `python
    # analisis_n1.py` seria una trampa. Para un resultado citable con
    # limites, usar muestra_n1_con_limites.py (muestra dirigida, ~3 h).
    if con_limites and args.tipo == 'todos' and not args.forzar:
        print("El barrido COMPLETO con limites de reactivo cuesta ~170 h "
              "(~187 s x 3.277 contingencias, medido).\n"
              "Opciones:\n"
              "  - muestra dirigida y citable (~3 h):  python muestra_n1_con_limites.py\n"
              "  - baseline historico sin limites (~25 min, NO fisico): "
              "python analisis_n1.py --sin-limites\n"
              "  - un subconjunto con limites:          python analisis_n1.py --tipo trafo\n"
              "  - correrlo igual, a sabiendas:         python analisis_n1.py --forzar")
        return 1

    tipos = {'linea': ('Line',), 'trafo': ('Transformer',),
             'generador': ('Generator',),
             'todos': ('Line', 'Transformer', 'Generator')}[args.tipo]

    base, base_diag = caso_base(con_limites=con_limites, red=args.red)
    candidatos = elementos_de(base, tipos)
    if not candidatos:
        print("Ningun elemento cumple los filtros.")
        return 1

    # El nombre del CSV canonico (contingencias_n1.csv, el que cita el
    # README y el informe) solo se escribe en un barrido COMPLETO
    # (--tipo todos). Cualquier subconjunto (--tipo linea/trafo/generador)
    # escribe a un nombre distinto - ver el hallazgo I5 del sub-proyecto F:
    # un `--tipo linea` de verificacion sobreescribio por accidente el
    # barrido completo de 3.277 filas con uno de solo 942 generadores.
    # `--csv` sigue siendo la via explicita para apuntar a otro archivo.
    sufijo = '' if args.red == 'escenario' else f'_{args.red}'
    base_name = (f'contingencias_n1{sufijo}' if con_limites
                 else f'contingencias_n1{sufijo}_sin_limites')
    nombre_csv = f'{base_name}.csv' if args.tipo == 'todos' else f'{base_name}_{args.tipo}.csv'
    csv_path = Path(args.csv or config.salida(nombre_csv))

    # El parcial va a un fichero APARTE, no al definitivo: asi un barrido
    # a medias nunca se confunde con uno terminado. Al final se borra.
    parcial = csv_path.with_suffix('.parcial.csv')

    d = barrido(base, candidatos, con_limites=con_limites,
                csv_parcial=parcial)
    informe(d, args.top)

    d.to_csv(csv_path, index=False, encoding='utf-8-sig')
    if parcial.exists():
        parcial.unlink()
    print(f"\nResultado completo en '{csv_path}'")
    return 0


if __name__ == '__main__':
    sys.exit(main())
