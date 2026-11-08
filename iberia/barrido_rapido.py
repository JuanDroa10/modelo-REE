"""Barrido N-1 asequible: de 38,5 h a ~20 min, sin recortar cobertura.

Fase 2 del plan del 1-nov-2026. El barrido con limites de reactivo
costaba 42,3 s por contingencia x 3.277 = 38,5 h, que no es viable. Este
modulo lo ataca con TRES palancas independientes que se multiplican:

  (a) ARRANQUE EN CALIENTE.  El 98 % del coste son 14 flujos AC por
      contingencia, y son la redescubierta desde cero de un reparto
      PV/PQ que el caso base YA conoce. Sembrando el lazo con el del
      caso base: 34,3 -> 5,7 s por contingencia, **x6,04**, y
      verificar_arranque_caliente.py comprueba que el resultado es
      EXACTAMENTE el mismo, campo a campo.

  (b) PARALELIZACION.  Las contingencias son independientes. Cada
      trabajador carga la red una vez y procesa muchas. OMP_NUM_THREADS=1
      por proceso: sin eso cada uno lanza sus propios hilos BLAS y
      compiten entre si, que es peor que no paralelizar.

  (c) FILTRO TOPOLOGICO.  No todas las contingencias necesitan un flujo
      AC. Las ramas PUENTE -679 de 2.335, el 29 %- parten la red al
      salir: que carga queda aislada es TEORIA DE GRAFOS, deterministica,
      y hoy se les resuelve un flujo AC para llegar a esa misma
      respuesta. Los generadores por debajo de un umbral son un problema
      de balance, no de red.

ESTO NO RECORTA COBERTURA: LA RECLASIFICA. Las 3.277 contingencias se
analizan todas; lo que cambia es que cada una se resuelve con el metodo
que le corresponde. El CSV de salida las lleva todas, con una columna
`metodo` que dice como se obtuvo cada fila.

Uso:
    python barrido_rapido.py --plan                 # solo el reparto y el coste
    python barrido_rapido.py --red apagon
    python barrido_rapido.py --red apagon --procesos 8 --limite 200
"""
import argparse
import os

# UN SOLO HILO BLAS POR PROCESO, Y ANTES DE IMPORTAR NUMPY.
#
# Esto tiene que ir aqui arriba, no dentro del inicializador del
# trabajador: numpy/BLAS leen estas variables EN EL MOMENTO DEL IMPORT, y
# con `spawn` (el arranque por defecto en macOS) el hijo reimporta este
# modulo entero -incluido el `import numpy` de abajo- ANTES de ejecutar
# ninguna funcion. Ponerlas en el inicializador llegaba tarde.
#
# No es cosmetica. Con 8 procesos lanzando cada uno sus propios hilos
# BLAS, el barrido de punta murio con
#     BLAS error: Parameter number 3 passed to cblas_dgemv had an
#     invalid value
# y se llevo el pool entero por delante a las 50 contingencias.
for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
           'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import time
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from iberia import config

# Generadores por debajo de esto no se simulan con flujo: su salida es un
# problema de balance de potencia, no de red. 978 generadores, de los que
# 443 estan por debajo de 10 MW.
P_MIN_GENERADOR_MW = 10.0

# PAISES MODELADOS COMO AGREGADO. Portugal y Francia son 4 buses
# ficticios por pais, con UN generador por tecnologia que representa la
# flota ENTERA de ese pais en ese bus: FR_Nuclear_FR00742 son
# 10.255 MW, toda la nuclear francesa de ese nudo.
#
# Para esos generadores la contingencia N-1 NO ESTA DEFINIDA: quitar uno
# no es perder una maquina, es borrar 10 GW de golpe, que es un escenario
# catastrofico y no un fallo simple. El primer barrido los reportaba como
# "no converge", mezclando una limitacion conocida del modelo con un
# resultado del analisis. Se excluyen y se cuentan aparte.
#
# Sus LINEAS si se conservan: perder un interconector con Francia o
# Portugal es una contingencia N-1 real y perfectamente definida.
PAISES_AGREGADOS = ('FR', 'PT')

_CTX = {}


def _init_worker(red, semilla):
    """Cada proceso carga la red UNA vez y se queda con ella.

    Las variables de hilos BLAS NO se ponen aqui: ya estan puestas en la
    cabecera del modulo, que es el unico sitio donde llegan a tiempo.
    """
    warnings.filterwarnings('ignore')
    logging.disable(logging.INFO)
    import pypsa
    from iberia import analisis_n1 as an
    n = pypsa.Network(config.red_de(red))
    an.preparar_para_flujo_ac(n)
    n.pf()
    _CTX['base'] = n
    _CTX['semilla'] = semilla
    _CTX['an'] = an


def _trabajo(arg):
    tipo, nombre = arg
    an = _CTX['an']
    try:
        r = an.simular(_CTX['base'], tipo, nombre, con_limites=True,
                       fijados_iniciales=_CTX['semilla'])
    except Exception as e:                       # noqa: BLE001
        return {'tipo': tipo, 'elemento': nombre, 'convergio': False,
                'motivo': type(e).__name__, 'metodo': 'AC (error)'}
    if r is None:
        return None
    r['metodo'] = 'AC'
    return r


def clasificar(n):
    """Reparte las contingencias en las tres clases. Devuelve
    (puentes, mallados, gen_grandes, gen_pequenos)."""
    import networkx as nx
    G = nx.Graph()
    for _, r in n.lines.iterrows():
        G.add_edge(r.bus0, r.bus1)
    for _, r in n.transformers.iterrows():
        G.add_edge(r.bus0, r.bus1)
    puentes = set(map(frozenset, nx.bridges(G)))

    es_puente, mallados = [], []
    for tabla, tipo in ((n.lines, 'Line'), (n.transformers, 'Transformer')):
        for k, r in tabla.iterrows():
            destino = es_puente if frozenset((r.bus0, r.bus1)) in puentes else mallados
            destino.append((tipo, k))

    g = n.generators
    agregado = g.bus.str.startswith(PAISES_AGREGADOS)
    excluidos = [('Generator', k) for k in g.index[agregado]]
    propios = g[~agregado]
    grandes = [('Generator', k)
               for k in propios.index[propios.p_set.abs() >= P_MIN_GENERADOR_MW]]
    pequenos = [('Generator', k)
                for k in propios.index[propios.p_set.abs() < P_MIN_GENERADOR_MW]]
    return es_puente, mallados, grandes, pequenos, excluidos


def resolver_deterministas(base, puentes, pequenos):
    """Las clases que NO necesitan flujo AC.

    Un PUENTE, al salir, parte la red: `separar_islas` dice exactamente
    que carga y que generacion quedan aisladas. Eso es el resultado
    completo de la contingencia para esa clase, y no hay nada que un
    flujo AC pueda anadir sobre el reparto - solo sobre el estado de la
    parte que sigue en pie, que es justo lo que un barrido N-1 clasico
    tampoco reporta cuando la red se parte.

    Un GENERADOR PEQUENO (< P_MIN_GENERADOR_MW) al salir es un desbalance
    de unos pocos MW que la regulacion absorbe: no es un problema de red.
    """
    from iberia import analisis_n1 as an
    filas = []
    for tipo, nombre in puentes:
        n = base.copy()
        if nombre not in an._tabla(n, tipo).index:
            continue
        n.remove(tipo, nombre)
        carga, gen, islas, carga_ib = an.separar_islas(n)
        filas.append({'tipo': tipo, 'elemento': nombre, 'islas': islas,
                      'MW_desconectados': round(carga, 1),
                      'MW_desconectados_iberia': round(carga_ib, 1),
                      'MW_gen_perdida': round(gen, 1),
                      'convergio': True, 'motivo': '',
                      'carga_max_pct': np.nan, 'n_sobrecargas': 0,
                      'v_min': np.nan, 'v_max': np.nan,
                      'n_v_bajas': 0, 'n_v_altas': 0, 'elemento_critico': '',
                      'n_fuera_curva_q': 0, 'metodo': 'grafo (puente)'})
    for tipo, nombre in pequenos:
        if nombre not in base.generators.index:
            continue
        p = float(base.generators.at[nombre, 'p_set'])
        filas.append({'tipo': tipo, 'elemento': nombre, 'islas': 1,
                      'MW_desconectados': 0.0, 'MW_desconectados_iberia': 0.0,
                      'MW_gen_perdida': round(abs(p), 1),
                      'convergio': True, 'motivo': '',
                      'carga_max_pct': np.nan, 'n_sobrecargas': 0,
                      'v_min': np.nan, 'v_max': np.nan,
                      'n_v_bajas': 0, 'n_v_altas': 0, 'elemento_critico': '',
                      'n_fuera_curva_q': 0, 'metodo': 'balance (gen < umbral)'})
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    config.anadir_arg_red(ap, por_defecto='apagon')
    ap.add_argument('--procesos', type=int, default=8,
                    help="trabajadores en paralelo (10 nucleos; 8 deja margen)")
    ap.add_argument('--limite', type=int, default=0,
                    help="solo las N primeras de la clase AC, para probar")
    ap.add_argument('--plan', action='store_true',
                    help="solo muestra el reparto y el coste estimado")
    args = ap.parse_args()

    import pypsa
    from iberia import analisis_n1 as an
    from iberia import limites_reactivos_espana as L

    print("BARRIDO N-1 RAPIDO")
    print("=" * 68)
    print(f"  punto de operacion: {args.red}")
    # `con_limites` de caso_base solo cambia el DIAGNOSTICO que informa -la
    # red devuelta es la misma-, y calcularlo cuesta el lazo de reactivo
    # entero, minutos en la punta. El --plan solo cuenta contingencias por
    # clase, que es topologia y p_set: no lo necesita.
    base, _ = an.caso_base(verbose=False, con_limites=not args.plan,
                           red=args.red)
    puentes, mallados, grandes, pequenos, excluidos = clasificar(base)
    ac = mallados + grandes
    total = len(puentes) + len(mallados) + len(grandes) + len(pequenos)

    print(f"\n  REPARTO de las {total} contingencias:")
    print(f"    ramas PUENTE          {len(puentes):5d}   grafo, sin flujo AC")
    print(f"    generadores < {P_MIN_GENERADOR_MW:.0f} MW   {len(pequenos):5d}   balance, sin flujo AC")
    print(f"    ramas MALLADAS        {len(mallados):5d}   flujo AC con limites de Q")
    print(f"    generadores >= {P_MIN_GENERADOR_MW:.0f} MW  {len(grandes):5d}   flujo AC con limites de Q")
    print(f"    {'':22s} {len(ac):5d}   TOTAL con flujo AC")
    print(f"\n    EXCLUIDOS: {len(excluidos)} generadores de "
          f"{'/'.join(PAISES_AGREGADOS)} (agregados de pais: su N-1 no esta "
          f"definido)")

    seg = 5.7
    print(f"\n  COSTE estimado (5,7 s/caso con arranque en caliente):")
    print(f"    sin paralelizar      : {len(ac)*seg/3600:6.2f} h")
    print(f"    con {args.procesos} procesos      : {len(ac)*seg/3600/args.procesos:6.2f} h")
    print(f"    (sin ninguna palanca : {total*42.3/3600:6.2f} h)")
    if args.plan:
        return

    print("\n  resolviendo las clases deterministas ...", flush=True)
    t0 = time.time()
    filas = resolver_deterministas(base, puentes, pequenos)
    print(f"    {len(filas)} contingencias en {time.time()-t0:.1f} s")

    base_lim, info = L.aplicar(base, verbose=False)
    semilla = info['conmutados']
    print(f"  semilla del arranque en caliente: {len(semilla)} generadores a PQ")

    if args.limite:
        ac = ac[:args.limite]
    print(f"\n  flujo AC sobre {len(ac)} contingencias, {args.procesos} procesos ...",
          flush=True)
    salida = config.salida(f'contingencias_n1_{args.red}.csv')
    # LOS PUNTOS DE CONTROL VAN A UN FICHERO APARTE (corregido el 4-nov-2026).
    #
    # Antes se volcaban cada 50 contingencias SOBRE `salida`, el fichero de
    # resultado. Asi que cualquier barrido interrumpido -un Ctrl-C, un corte,
    # un proceso que muere- dejaba en su sitio un CSV PARCIAL en lugar del
    # barrido bueno anterior, y todo lo que lo lee despues (el ranking del
    # menu, estado_actual, las figuras del N-1) lo tomaba por valido sin
    # aviso. Paso de verdad: interrumpir el barrido del apagon desde el menu a
    # los 50 casos de flujo AC reemplazo las 3.277 filas comiteadas por 1.172.
    #
    # Ahora el progreso se guarda en `parcial`, y `salida` solo se sustituye
    # al TERMINAR, y de forma atomica (os.replace): o queda el barrido viejo
    # entero, o el nuevo entero, nunca una mezcla.
    parcial = salida[:-len('.csv')] + '.parcial.csv'

    # EL POOL SE RECONSTRUYE SI UN TRABAJADOR MUERE.
    #
    # Un unico proceso que cae -por un fallo de BLAS, por memoria, por una
    # red degenerada que hace singular el jacobiano- se lleva por delante
    # TODO el pool con BrokenProcessPool, y con el las contingencias ya
    # calculadas que aun no se habian volcado. Paso de verdad en el
    # barrido de punta, a las 50 de 2.045.
    #
    # Se usa submit() en vez de map() para saber EXACTAMENTE cual se
    # quedo sin resolver, se reconstruye el pool y se sigue con las que
    # faltan. La contingencia que provoco la caida se marca y no se
    # reintenta indefinidamente.
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures.process import BrokenProcessPool
    t0 = time.time()
    pendientes = list(ac)
    caidas = []
    rondas = 0
    while pendientes and rondas < 6:
        rondas += 1
        if rondas > 1:
            print(f"    [pool reconstruido, ronda {rondas}: quedan "
                  f"{len(pendientes)}]", flush=True)
        quedan = []
        try:
            with ProcessPoolExecutor(max_workers=args.procesos,
                                     initializer=_init_worker,
                                     initargs=(args.red, semilla)) as ex:
                futuros = {ex.submit(_trabajo, a): a for a in pendientes}
                quedan = list(pendientes)
                for fut in as_completed(futuros):
                    arg = futuros[fut]
                    try:
                        r = fut.result()
                    except BrokenProcessPool:
                        # EL POOL HA MUERTO, NO ESTA CONTINGENCIA.
                        #
                        # Cuando un trabajador cae, TODOS los futuros
                        # pendientes lanzan BrokenProcessPool al pedir su
                        # resultado. Capturarlo aqui como "fallo de esta
                        # contingencia" convertia una caida del pool en
                        # 1.973 resultados FALSOS de "no converge", y el
                        # barrido terminaba "con exito" en 2,9 min
                        # habiendo resuelto 72 casos. Paso de verdad en
                        # el primer intento de punta.
                        #
                        # Se relanza para que lo recoja el `except` de
                        # fuera, que reconstruye el pool y reintenta SOLO
                        # lo que quedaba.
                        raise
                    except Exception as e:              # noqa: BLE001
                        # Un fallo de ESTA contingencia (red degenerada,
                        # jacobiano singular...): eso si es un resultado.
                        r = {'tipo': arg[0], 'elemento': arg[1],
                             'convergio': False, 'motivo': type(e).__name__,
                             'metodo': 'AC (fallo)'}
                    if r is not None:
                        filas.append(r)
                    quedan.remove(arg)
                    hechas = len(ac) - len(quedan)
                    if hechas % 50 == 0 or not quedan:
                        t = time.time() - t0
                        resta = t / max(hechas, 1) * len(quedan)
                        print(f"    {hechas}/{len(ac)}  {t/60:.1f} min, "
                              f"quedan ~{resta/60:.1f} min", flush=True)
                        pd.DataFrame(filas).to_csv(parcial, index=False,
                                                   encoding='utf-8-sig')
        except BrokenProcessPool:
            print(f"    AVISO: un trabajador murio; {len(quedan)} sin "
                  f"resolver, reconstruyendo el pool", flush=True)
            pd.DataFrame(filas).to_csv(parcial, index=False,
                                       encoding='utf-8-sig')
            # Si solo queda una, es ella la que tumba el proceso de
            # forma reproducible: se marca y se sigue.
            if len(quedan) == 1:
                caidas.extend(quedan)
                quedan = []
        pendientes = quedan
    for tipo, nombre in caidas + pendientes:
        filas.append({'tipo': tipo, 'elemento': nombre, 'convergio': False,
                      'motivo': 'tumba el proceso', 'metodo': 'AC (fallo)'})
    if caidas or pendientes:
        print(f"    {len(caidas)+len(pendientes)} contingencias tumbaron su "
              f"proceso y se marcan como fallo, no como resultado")

    d = pd.DataFrame(filas)
    d['severidad'] = d.apply(an.severidad, axis=1)
    d = d.sort_values('severidad', ascending=False).reset_index(drop=True)
    temporal = salida + '.tmp'
    d.to_csv(temporal, index=False, encoding='utf-8-sig')
    os.replace(temporal, salida)
    if os.path.exists(parcial):
        os.remove(parcial)

    # LA METRICA ES INCREMENTAL, NO ABSOLUTA.
    #
    # El caso base ya arrastra sobrecargas propias (12 en el apagon, 40 en
    # la punta), asi que casi cualquier contingencia las HEREDA y, contada
    # en absoluto, sale "con sobrecargas" sin haber causado ninguna. La
    # primera version de este resumen informaba 2.183 de 2.191 (99,6%),
    # una cifra sospechosamente parecida al 3.276 de 3.277 del barrido
    # historico que ya se habia retirado por no fisico - y por la misma
    # clase de motivo: contar un defecto preexistente como si lo causara
    # la contingencia.
    #
    # Lo que un N-1 debe medir es lo que la contingencia ANADE.
    est_base = an.estado(base_lim)
    sob_base = len(est_base['sobrecargados'])
    carga_base = est_base['carga_max_pct']
    ac_d = d[d.metodo == 'AC']
    nuevas = ac_d[ac_d.n_sobrecargas > sob_base]
    peores = ac_d[ac_d.carga_max_pct > carga_base + 1e-6]
    alivian = ac_d[ac_d.n_sobrecargas < sob_base]

    fallos = int((d.metodo == 'AC (fallo)').sum()) if 'metodo' in d else 0
    if fallos > 0.05 * max(len(ac), 1):
        print(f"\n  *** BARRIDO INCOMPLETO ***")
        print(f"  {fallos} de {len(ac)} contingencias AC no se resolvieron.")
        print(f"  Las cifras de abajo NO son un resultado del sistema: son")
        print(f"  lo poco que se llego a calcular. NO CITAR.")
    print(f"\n--- Resultado ---")
    print(f"  contingencias       : {len(d)} de {total}")
    print(f"  tiempo del flujo AC : {(time.time()-t0)/60:.1f} min")
    print(f"  por metodo          : {d.metodo.value_counts().to_dict()}")
    print(f"\n  REFERENCIA del caso base: {sob_base} sobrecargas, "
          f"cargabilidad maxima {carga_base:.1f} %")
    print(f"  (todo lo de abajo se mide CONTRA esa referencia, no en absoluto)")
    print(f"\n  no convergen                      : {int((~d.convergio).sum()):5d}")
    print(f"  CREAN sobrecargas nuevas          : {len(nuevas):5d} de {len(ac_d)} "
          f"({100*len(nuevas)/max(len(ac_d),1):.1f} %)")
    # LA DISTRIBUCION, NO EL RECUENTO.
    #
    # "empeoran la cargabilidad" con umbral cero daba el 86 %, que es
    # otra cifra enganosa: quitar cualquier rama redistribuye el flujo y
    # casi siempre sube el maximo unas decimas. Medido en el apagon: de
    # 2.155 casos, 1.697 la MEJORAN, 364 suben menos de 1 punto -ruido
    # numerico- y solo 16 pasan de +50. Lo que importa es cuanto, no
    # cuantos.
    delta = ac_d.carga_max_pct - carga_base
    bandas = [(-1e9, 0.0, 'la mejoran o igual'),
              (0.0, 1.0, '+0 a +1 pp (ruido)'),
              (1.0, 5.0, '+1 a +5 pp'),
              (5.0, 20.0, '+5 a +20 pp'),
              (20.0, 50.0, '+20 a +50 pp'),
              (50.0, 1e9, 'mas de +50 pp  <<< SEVERAS')]
    # OJO AL LEER LAS DOS PRIMERAS BANDAS: estan dominadas por el ruido
    # y por donde cae la referencia. Al pasar P_NOM_MIN_PV de 1 a 25 MW
    # la referencia del apagon se movio de 121,8 a 121,7 % -una decima- y
    # 1.451 casos saltaron de "la mejoran o igual" a "+0 a +1 pp", sin que
    # cambiara nada fisico. Sumarlas para decir "el 82 % de las
    # contingencias empeoran la red" seria una cifra vacia.
    #
    # Lo estable son las bandas de arriba: las severas (+50 pp) y, sobre
    # todo, "CREAN sobrecargas nuevas", que es un conteo discreto y no se
    # mueve con la referencia. En la comparacion de los dos barridos del
    # apagon, los veredictos -convergencia, n_sobrecargas, MW aislados-
    # salieron IDENTICOS en las 3.277 contingencias.
    print(f"  cuanto empeoran la cargabilidad maxima:")
    for lo, hi, etq in bandas:
        m = (delta <= hi) if lo < -1e8 else ((delta > lo) & (delta <= hi))
        print(f"      {etq:28s} {int(m.sum()):5d}")
    print(f"  ALIVIAN sobrecargas del caso base : {len(alivian):5d}")
    ib = d.MW_desconectados_iberia
    print(f"  aislan carga ESPANOLA             : {int((ib > 0.1).sum()):5d}  "
          f"(peor: {ib.max():,.1f} MW)")
    solo_fr = int(((d.MW_desconectados > 0.1) & (ib <= 0.1)).sum())
    print(f"  aislan solo carga agregada FR/PT : {solo_fr:5d}  "
          f"(no miden la red espanola, ver separar_islas)")
    if len(peores):
        print(f"  peor cargabilidad alcanzada       : {peores.carga_max_pct.max():.1f} %")
    print(f"\n  CSV en {salida}")


if __name__ == '__main__':
    main()
