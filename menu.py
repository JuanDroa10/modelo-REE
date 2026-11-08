# menu.py
"""Consola interactiva del modelo iberico.

Reune en un solo sitio todo lo que el modelo sabe hacer, para no tener que
recordar que modulo y que banderas corresponden a cada cosa.

    python menu.py

Tiene la misma forma que la consola del modelo del STN colombiano a
proposito: los dos modelos comparan los mismos analisis sobre dos sistemas
distintos, y dos consolas iguales hacen que la comparacion sea de los
SISTEMAS y no de lo que cada consola decidio enseñar.

POR QUE MERECE LA PENA, mas alla de agrupar ordenes: construir y resolver el
caso base con limites de reactivo cuesta alrededor de 1 min en cualquier
punto de operacion. Aqui se construye UNA VEZ por sesion y se reutiliza, de
modo que preguntar por una barra, por el BTM o por el balance por pais es
inmediato a partir de la segunda vez.

Las simulaciones largas -barridos N-1, calibraciones- se lanzan en un proceso
aparte, porque modifican la red y no conviene que contaminen el caso base
cacheado.

Sin dependencias fuera de la libreria estandar y de lo que el modelo ya usa.
"""

import os
import subprocess
import sys
import textwrap
import time

os.environ.setdefault('PYTHONWARNINGS', 'ignore')

ANCHO = 78
_BASE = {}          # cache del caso base de esta sesion

# Punto de operacion ACTIVO. Se elige al entrar y vale para toda la sesion:
# tanto para las simulaciones, que se lanzan en otro proceso con --red, como
# para las consultas, que leen el caso cacheado. Las dos cosas TIENEN que
# salir del mismo sitio, o el menu enseña consultas de un sistema y
# simulaciones de otro. (Es el defecto que el menu del STN ya tuvo y corrigio;
# aqui nace corregido.)
_PUNTO = {'tipo': 'apagon', 'etiqueta': '28-abr-2025 12:33 (apagon iberico)'}

_ESCENARIOS = [
    ('apagon', '28-abr-2025 12:33 (apagon iberico)',
     'RECONSTRUIDO de fuentes secundarias; el N-1 corre sobre un caso '
     'base LIMPIO', '92'),
    ('punta', '15-ene 20-21 h (punta invernal nocturna)',
     'DERIVADO; su caso base arranca con 5 sobrecargas (despacho sin '
     'orden de merito): el N-1 se cita contra esa referencia', '93'),
    ('escenario', 'exportacion generica de 3.000 MW (despacho uniforme)',
     'SINTETICO; no representa ninguna hora real', '93'),
]


# ---------------------------------------------------------------------------
# Presentacion
# ---------------------------------------------------------------------------

def _c(txt, code):
    """Color ANSI, solo si la salida es un terminal de verdad."""
    return f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else txt


def titulo(txt):
    print()
    print(_c("=" * ANCHO, '90'))
    print(_c(f" {txt}", '1'))
    print(_c("=" * ANCHO, '90'))


def parrafo(txt, sangria='   '):
    for linea in textwrap.wrap(' '.join(txt.split()), ANCHO - len(sangria)):
        print(sangria + linea)


def pausa():
    try:
        input(_c("\n   [Enter] para volver al menu ", '90'))
    except EOFError:
        pass


def confirmar(texto):
    """Si/no, con NO por defecto: un Enter de mas nunca lanza nada caro."""
    try:
        r = input(_c(f"   {texto} [s/N]: ", '93')).strip().lower()
    except EOFError:
        return False
    return r in ('s', 'si', 'sí', 'y', 'yes')


def preguntar(texto, defecto=None, tipo=str):
    suf = f" [{defecto}]" if defecto is not None else ""
    while True:
        try:
            v = input(_c(f"   {texto}{suf}: ", '96')).strip()
        except EOFError:
            return defecto
        if not v:
            return defecto
        try:
            return tipo(v)
        except ValueError:
            print(_c("   valor no valido", '91'))


def elegir(texto, opciones, defecto=0):
    print(f"   {texto}")
    for i, o in enumerate(opciones):
        marca = '*' if i == defecto else ' '
        print(f"     {marca} {i+1}) {o}")
    v = preguntar("numero", defecto + 1, int)
    return opciones[v - 1] if 1 <= v <= len(opciones) else opciones[defecto]


# ---------------------------------------------------------------------------
# Caso base cacheado
# ---------------------------------------------------------------------------

def base(con_limites=True, verbose=True):
    """Caso base resuelto, construido una sola vez por sesion.

    `con_limites=True` devuelve la red con los limites de capacidad de
    reactivo YA aplicados (generadores conmutados a PQ). Es lo que debe
    usar cualquier consulta, porque la red SIN conmutar no es un punto de
    operacion fisicamente valido: deja maquinas produciendo reactivo que
    no pueden entregar.

    Esto es exactamente la trampa que `analisis_n1.caso_base` documenta en
    su docstring -la red que devuelve y el diagnostico que informa NO son
    el mismo estado- y la razon de que el menu aplique los limites el
    mismo en vez de fiarse del diagnostico.

    Devuelve (network, info_del_lazo). La red se entrega SIN copiar: quien
    la vaya a modificar debe llamar a .copy() primero.
    """
    clave = ('lim' if con_limites else 'crudo', _PUNTO['tipo'])
    if clave not in _BASE:
        if verbose:
            print(_c(f"\n   construyendo {_PUNTO['etiqueta']} "
                     f"(solo la primera vez)...", '90'))
            if _PUNTO['tipo'] == 'punta' and con_limites:
                print(_c("   la punta tarda alrededor de 1 min: su lazo de "
                         "reactivo no converge a la primera", '90'))
        t0 = time.time()
        from iberia import analisis_n1 as an
        # `con_limites` de caso_base solo cambia el DIAGNOSTICO que informa,
        # pero calcularlo cuesta el lazo entero -minutos en la punta-. Si
        # aqui no se van a aplicar los limites, ese diagnostico se iba a
        # tirar: no se pide.
        n, diag = an.caso_base(verbose=False, con_limites=con_limites,
                               red=_PUNTO['tipo'])
        info = {}
        if con_limites:
            from iberia import limites_reactivos_espana as L
            n, info = L.aplicar(n, verbose=False)
        _BASE[clave] = (n, info)
        if verbose:
            print(_c(f"   listo en {time.time()-t0:.0f} s", '90'))
    return _BASE[clave]


def sistema():
    """Objeto Sistema (H, S_base, reserva...), tambien cacheado."""
    clave = ('sis', _PUNTO['tipo'])
    if clave not in _BASE:
        from iberia import dinamica_frecuencia as din
        # Sobre la red SIN conmutar: el Sistema solo lee placa, despacho y
        # tecnologia, que los limites de reactivo no tocan, y asi no hay
        # que esperar al lazo para una consulta de inercia.
        import pypsa
        from iberia import config
        _BASE[clave] = din.Sistema(pypsa.Network(config.red_de(_PUNTO['tipo'])))
    return _BASE[clave]


def num_de(fragmento):
    """Numero de menu, EN EL PUNTO ACTIVO, de la opcion cuyo nombre contiene
    `fragmento`; 0 si en este punto no se ofrece.

    Las referencias cruzadas escritas a mano se desincronizan en cuanto se
    inserta una opcion, y ahora ademas la numeracion cambia de un punto a
    otro, porque cada uno oculta las que no le aplican."""
    for i, op in enumerate(numeradas(), 1):
        if fragmento.lower() in op['nombre'].lower():
            return i
    return 0


def correr(args):
    """Lanza un modulo del modelo en un proceso aparte.

    SIEMPRE enseña la orden que construyo: un menu que no enseña las
    banderas que emite es una caja negra, y es asi como sobreviven los
    desajustes entre lo que el menu cree pedir y lo que el modulo
    entiende."""
    print(_c(f"\n   $ python -m {' '.join(args)}", '90'))
    print()
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, '-m'] + args, check=False,
                           cwd=RAIZ)
    except KeyboardInterrupt:
        print(_c("\n   interrumpido", '93'))
        return False
    if r.returncode != 0:
        print(_c(f"\n   el modulo termino con codigo {r.returncode}: "
                 f"la salida de arriba no es un resultado valido", '91'))
    print(_c(f"\n   ({time.time()-t0:.0f} s)", '90'))
    return r.returncode == 0


def _red():
    """Banderas de linea de ordenes del punto de operacion ACTIVO."""
    return ['--red', _PUNTO['tipo']]


def elegir_punto(primera_vez=False):
    """Pide el punto de operacion. Devuelve True si cambio, False si no, y
    None si el usuario sale con `q` (solo en la primera pantalla)."""
    if primera_vez:
        titulo("SOBRE QUE PUNTO DE OPERACION QUIERES TRABAJAR")
        print()
        parrafo("Vale para TODA la sesion: las opciones del menu se adaptan al "
                "punto elegido, y las que no dependen de el se agrupan aparte. "
                "Se puede cambiar luego con la opcion `p`.")
        print()
    for i, (clave, etq, aval, color) in enumerate(_ESCENARIOS):
        marca = '*' if clave == _PUNTO['tipo'] else ' '
        print(f"     {marca} {i+1}) {etq}")
        print(f"          {_c(aval, color)}")
    if primera_vez:
        print(f"       {_c('q', '96')}) salir")
    while True:
        try:
            v = input(_c("   numero [1]: ", '96')).strip().lower()
        except EOFError:
            v = ''
        if primera_vez and v in ('q', 'salir'):
            return None
        if not v:
            v = '1' if primera_vez else str(
                1 + [e[0] for e in _ESCENARIOS].index(_PUNTO['tipo']))
        if v.isdigit() and 1 <= int(v) <= len(_ESCENARIOS):
            break
        print(_c("   valor no valido", '91'))
    nuevo = _ESCENARIOS[int(v) - 1]
    cambio = nuevo[0] != _PUNTO['tipo']
    _PUNTO['tipo'], _PUNTO['etiqueta'] = nuevo[0], nuevo[1]
    if cambio:
        _BASE.clear()
    return cambio


# ---------------------------------------------------------------------------
# 1. Simulaciones (proceso aparte)
# ---------------------------------------------------------------------------

def sim_entsoe():
    correr(['iberia.validar_traza_28a'])


def sim_n1():
    print()
    parrafo("El barrido completo son 3.277 contingencias. No todas necesitan "
            "flujo AC: las ramas PUENTE se resuelven por teoria de grafos "
            "(su salida aisla, no redistribuye) y los generadores pequeños "
            "por balance. Eso deja unas 2.045 con flujo AC de verdad.")
    print()
    op = elegir("que quieres hacer", [
        'barrido completo del punto activo  (34 min apagon / 138 min punta)',
        'solo el PLAN: cuantas contingencias de cada clase y cuanto costaria',
        'una contingencia concreta, elegida por nombre',
        'el ranking de las mas graves del ultimo barrido'])
    if op.startswith('barrido completo'):
        print()
        parrafo("Al TERMINAR, sustituye el barrido guardado de este punto "
                "(resultados/contingencias_n1_<punto>.csv). Si se "
                "interrumpe, el guardado no se toca: el progreso va a un "
                "fichero .parcial aparte.")
        if not confirmar("lanzar el barrido completo?"):
            print(_c("   cancelado", '90'))
            return
        p = preguntar("procesos en paralelo", 8, int)
        correr(['iberia.barrido_rapido'] + _red() + ['--procesos', str(p)])
    elif op.startswith('solo el PLAN'):
        correr(['iberia.barrido_rapido'] + _red() + ['--plan'])
    elif op.startswith('una contingencia'):
        e = preguntar("nombre del elemento (p.ej. L1357, G0911)", "")
        if e:
            _una_contingencia(e)
    else:
        _ranking_n1()


def _una_contingencia(elemento):
    # CRUDA, no conmutada. `analisis_n1.simular` aplica los limites de
    # reactivo POR SU CUENTA, igual que hace el barrido. Pasarle la red que
    # ya paso por el lazo la haria partir de otro estado, y el resultado no
    # coincidiria con la fila del barrido para ese mismo elemento --- que es
    # justo para lo que sirve esta opcion.
    n, _ = base(con_limites=False)
    from iberia import analisis_n1 as an
    if elemento in n.lines.index:
        tipo = 'Line'
    elif elemento in n.transformers.index:
        tipo = 'Transformer'
    elif elemento in n.generators.index:
        tipo = 'Generator'
    else:
        print(_c(f"   '{elemento}' no esta en la red", '91'))
        return
    print(_c(f"\n   simulando la salida de {elemento} ({tipo})...", '90'))
    print(_c("   con limites de reactivo: puede tardar minutos", '90'))
    r = an.simular(n, tipo, elemento)
    print()
    for k, v in r.items():
        print(f"      {k:26s} {v}")


def _ranking_n1():
    import pandas as pd
    from iberia import analisis_n1 as an
    print()
    try:
        # el barrido propio si lo hay; si no, el de referencia del repositorio
        ruta, _ = an.fuente_n1(red=_PUNTO['tipo'])
    except SystemExit:
        print(_c(f"\n   no hay barrido para '{_PUNTO['tipo']}'. Correlo "
                 f"primero con la opcion del barrido completo.", '93'))
        return
    d = pd.read_csv(ruta)
    ac = d[d.metodo == 'AC']
    conv = ac[ac.convergio == True]                         # noqa: E712
    print()
    if len(conv) and conv.elemento_critico.nunique() == 1:
        unico = conv.elemento_critico.iloc[0]
        print(_c(f"   AVISO: el elemento critico es '{unico}' en LAS "
                 f"{len(conv)} contingencias resueltas.", '93'))
        parrafo("Eso no es un N-1 midiendo la red: es un defecto del caso "
                "base repetido una vez por contingencia. El ranking de abajo "
                "sigue valiendo como severidad RELATIVA, porque cada fila se "
                "mide contra la referencia del caso base, pero las "
                "cargabilidades absolutas no son citables.")
        print()
    n_mostrar = preguntar("cuantas", 15, int)
    cols = ['tipo', 'elemento', 'carga_max_pct', 'n_sobrecargas',
            'MW_desconectados_iberia', 'severidad']
    print()
    print(d.sort_values('severidad', ascending=False)
           .head(n_mostrar)[cols].to_string(index=False))


def sim_frecuencia():
    print()
    parrafo("Integra la ecuacion de oscilacion tras perder generacion de "
            "golpe, con los SEIS escalones del P.O. 1.6: dos de bombeo "
            "(49,5 y 49,3 Hz) y cuatro generales (49,0 / 48,7 / 48,4 / "
            "48,0 Hz).")
    s = sistema()
    mw = preguntar("MW de generacion que se pierden de golpe", 2000.0, float)
    con = elegir("esquema de deslastre",
                 ['activo (P.O. 1.6 completo)',
                  'activo pero SIN los escalones de bombeo (como Colombia)',
                  'desactivado'])
    from iberia import dinamica_frecuencia as din
    kw = {}
    if con.startswith('activo pero'):
        kw = {'umbrales_bombeo': (), 'fracciones_bombeo': ()}
    t, f, tr = din.simular_frecuencia(
        s, [{'t': 0.0, 'dP_gen': mw, 'etiqueta': 'perdida de generacion'}],
        con_deslastre=not con.startswith('desactivado'), **kw)
    print()
    print(f"      {din.describir(tr)}")
    print(f"      RoCoF inicial        {tr['rocof_inicial']:+.4f} Hz/s")
    print(f"      aporte de primaria   {tr['aporte_primaria']:8.1f} MW")
    print(f"      deslastre de clientes{tr['deslastre_total']:8.1f} MW")
    print(f"      bombeo soltado       {tr['bombeo_deslastrado']:8.1f} MW")
    print()
    for e in tr.get('escalones_bombeo', []):
        est = f"t={e['t_disparo']:.2f} s, {e['mw']:.0f} MW" if e['disparado'] \
            else 'no dispara'
        print(f"      bombeo  {e['umbral']:.1f} Hz   {est}")
    for e in tr['escalones']:
        est = f"t={e['t_disparo']:.2f} s, {e['mw']:.0f} MW" if e['disparado'] \
            else 'no dispara'
        print(f"      general {e['umbral']:.1f} Hz   {est}")


def sim_comparar():
    print()
    op = elegir("que comparo", [
        'todo menos la muestra N-1  (~2 min: resuelve los dos casos base)',
        'con la muestra N-1 de 6 contingencias por escenario  (~37 min)'])
    # La muestra N-1 es la parte cara, y ademas NO es un analisis N-1: son
    # las 6 contingencias dirigidas a los elementos mas cargados (ver el
    # analisis). Por defecto se omite.
    correr(['iberia.comparar_escenarios']
           + ([] if op.startswith('con la muestra') else ['--n1', '0']))


def sim_btm():
    caida = preguntar("% del BTM con inversor que se desconecta", 80.0, float)
    correr(['iberia.deslastre_btm_espana'] + _red() + ['--caida', str(caida)])


def sim_cascada():
    correr(['iberia.analisis_btm_cascada'] + _red())


def sim_mapa():
    # Los de resultados/visualizaciones/ salen de la red de construccion; los
    # de resultados/mapas/, de iberia.mapas. Ninguno depende del punto.
    correr(['iberia.visualize_network'])
    correr(['iberia.mapas', 'red'])
    correr(['iberia.mapas', 'btm'])


# ---------------------------------------------------------------------------
# 2. Consultas (sobre el caso cacheado)
# ---------------------------------------------------------------------------

def con_resumen():
    n, info = base()
    s = sistema()
    from iberia import analisis_n1 as an
    v = n.buses_t.v_mag_pu.iloc[0].astype(float)
    est = an.estado(n)
    es = n.buses[n.buses.index.str.startswith('ES')].index
    pt = n.buses[n.buses.index.str.startswith('PT')].index
    ib = list(es) + list(pt)
    g_ib = n.generators[n.generators.bus.isin(ib)].index
    c_ib = n.loads[n.loads.bus.isin(ib)].index
    gen = float(n.generators_t.p.iloc[0][g_ib].sum())
    car = float(n.loads_t.p.iloc[0][c_ib].sum())
    gen_t = float(n.generators_t.p.iloc[0].sum())
    car_t = float(n.loads_t.p.iloc[0].sum())
    print()
    print(f"   RED        {len(n.buses)} buses | {len(n.lines)} lineas | "
          f"{len(n.transformers)} trafos | {len(n.generators)} gen | "
          f"{len(n.loads)} cargas")
    print(f"              {len(es)} de red real (ES) | {len(pt)} PT + "
          f"{len(n.buses)-len(es)-len(pt)} FR, que son AGREGADOS de pais")
    # El balance que importa es el IBERICO. Incluir Francia -4 buses que
    # representan la flota francesa entera- diluye las perdidas.
    #
    # PERO generacion - demanda DENTRO de Iberia NO son las perdidas: ahi
    # va tambien la EXPORTACION a Francia. Mezclarlas da una cifra de
    # perdidas inflada (7,8% en el apagon, cuando lo que hay son 2.487 MW
    # de los que la mayoria cruzan la frontera). Se separan: el
    # intercambio se mide en las propias ramas transfronterizas.
    cruce = [l for l in n.lines.index
             if (n.lines.at[l, 'bus0'] in ib) != (n.lines.at[l, 'bus1'] in ib)]
    exporta = 0.0
    for l in cruce:
        p0 = float(n.lines_t.p0.iloc[0][l])
        # positivo = sale de Iberia
        exporta += p0 if n.lines.at[l, 'bus0'] in ib else -p0
    perdidas = gen - car - exporta
    print(f"   POTENCIA   IBERIA: generacion {gen:9.1f} MW | "
          f"demanda {car:9.1f} MW")
    print(f"              exporta a FR {exporta:8.1f} MW por {len(cruce)} "
          f"ramas | perdidas {perdidas:7.1f} MW "
          f"({100*perdidas/max(car,1):.2f} %)")
    print(f"              red entera (con FR): gen {gen_t:9.1f} | "
          f"dem {car_t:9.1f}  <- no citar: FR es contorno")
    print(f"   TENSION    [{v.min():.4f}, {v.max():.4f}] pu | "
          f"{len(est['v_bajas'])} bajas, {len(est['v_altas'])} altas")
    print(f"   CARGA      maxima {est['carga_max_pct']:.1f} % | "
          f"{len(est['sobrecargados'])} elementos sobre el 100 %")
    print(f"   FRECUENCIA H = {s.H:.3f} s | S_base = {s.S_base:.1f} MVA | "
          f"Ek = {s.H*s.S_base/1000:.1f} GW.s")
    print(f"              reserva primaria {s.reserva:.1f} MW")
    tercos = info.get('tercos') or []
    if tercos:
        print()
        print(_c(f"   AVISO: {len(tercos)} generador(es) no se pudieron "
                 f"meter en su curva de capacidad: {', '.join(tercos)}", '93'))
        parrafo("El caso base NO esta limpio: hay generadores pidiendo "
                "reactivo fuera de su curva, y la cargabilidad de este punto "
                "debe leerse con cuidado.")
    print()
    print("   MEZCLA POR TECNOLOGIA (MW de placa, solo Iberia)")
    ib = n.generators[n.generators.bus.isin(list(es) + list(pt))]
    for t, mw in ib.groupby('carrier').p_nom.sum().sort_values(
            ascending=False).head(12).items():
        desp = float(n.generators_t.p.iloc[0][
            ib[ib.carrier == t].index].sum())
        print(f"      {str(t):18s} {mw:9.1f}   despachados {desp:9.1f}")


def con_buscar():
    n, _ = base()
    q = preguntar("texto a buscar (nombre de barra, generador o linea)", "")
    if not q:
        return
    Q = q.upper()
    print()
    buses = [b for b in n.buses.index if Q in b.upper()][:10]
    if buses:
        print(_c("   BARRAS", '1'))
        for b in buses:
            gp = float(n.generators[n.generators.bus == b].p_nom.sum())
            cp = float(n.loads[n.loads.bus == b].p_set.sum())
            v = float(n.buses_t.v_mag_pu.iloc[0][b])
            print(f"      {b:12s} {n.buses.at[b,'v_nom']:5.0f} kV  "
                  f"v={v:.4f} pu | placa {gp:8.1f} MW | carga {cp:8.1f} MW")
            ramas = [l for l in n.lines.index
                     if n.lines.at[l, 'bus0'] == b or n.lines.at[l, 'bus1'] == b]
            for l in ramas[:12]:
                p = float(n.lines_t.p0.iloc[0][l])
                qq = float(n.lines_t.q0.iloc[0][l])
                pct = 100*(p**2 + qq**2)**0.5 / max(float(n.lines.at[l, 's_nom']), 1e-9)
                otro = (n.lines.at[l, 'bus1'] if n.lines.at[l, 'bus0'] == b
                        else n.lines.at[l, 'bus0'])
                col = '91' if pct > 100 else '90'
                print(f"         -> {l:8s} a {otro:10s} "
                      f"P={p:8.1f} Q={qq:8.1f} MVAr  "
                      + _c(f"({pct:.0f} % de s_nom)", col))
            if len(ramas) == 1:
                print(_c("         (grado 1: este nudo es RADIAL)", '93'))
    gens = [g for g in n.generators.index if Q in g.upper()][:15]
    if gens:
        print(_c("\n   GENERADORES", '1'))
        for g in gens:
            p = float(n.generators_t.p.iloc[0][g])
            qq = float(n.generators_t.q.iloc[0][g])
            print(f"      {g:12s} en {n.generators.at[g,'bus']:10s} "
                  f"{str(n.generators.at[g,'carrier']):16s} "
                  f"placa {n.generators.at[g,'p_nom']:8.1f} | "
                  f"P={p:8.1f} Q={qq:9.1f} MVAr | "
                  f"{n.generators.at[g,'control']}")
    lins = [l for l in n.lines.index if Q in l.upper()][:15]
    if lins:
        print(_c("\n   LINEAS", '1'))
        for l in lins:
            p = float(n.lines_t.p0.iloc[0][l])
            qq = float(n.lines_t.q0.iloc[0][l])
            snom = float(n.lines.at[l, 's_nom'])
            pct = 100*(p**2 + qq**2)**0.5/max(snom, 1e-9)
            print(f"      {l:8s} {n.lines.at[l,'bus0']:10s} -> "
                  f"{n.lines.at[l,'bus1']:10s} {n.lines.at[l,'length']:7.2f} km "
                  f"| P={p:8.1f} Q={qq:9.1f} | "
                  + _c(f"{pct:.1f} % de {snom:.0f} MVA",
                       '91' if pct > 100 else '90'))
    if not (buses or gens or lins):
        print(_c("   nada encontrado", '93'))


def con_btm():
    # Todo lo que hace falta aqui es estatico -placa, despacho, coordenadas y
    # p_set de las cargas-, asi que basta la red que ya leyo el Sistema.
    # Pedir base() costaba resolver el flujo AC con el lazo de reactivo,
    # minutos en la punta, para no usar ni un solo valor resuelto.
    n = sistema().network
    from iberia.btm_regional import (produccion_btm_por_bus, capacidad_btm_por_bus,
                              factor_produccion, region_de_bus)
    from iberia.deslastre_btm_espana import FRACCION_INVERSOR_BTM_ESPANA
    cap = capacidad_btm_por_bus(n)
    prod = produccion_btm_por_bus(n)
    es = n.buses[n.buses.index.str.startswith('ES')].index
    dem = float(n.loads[n.loads.bus.isin(es)].p_set.sum())
    print()
    print(f"   PLACA instalada    {float(cap.sum()):9.1f} MW en "
          f"{int((cap > 0).sum())} buses")
    print(f"   factor de produccion {factor_produccion(n):.4f} "
          f"(derivado de la FV espanola de ESTE snapshot)")
    print(f"   PRODUCIENDO ahora  {float(prod.sum()):9.1f} MW")
    print(f"   demanda espanola   {dem:9.1f} MW")
    print(f"   PENETRACION        {100*float(prod.sum())/max(dem,1):9.2f} % "
          f"de la demanda")
    print()
    print(f"   Por inversor: {100*FRACCION_INVERSOR_BTM_ESPANA:.1f} % "
          f"(el resto es cogeneracion, sincrona).")
    parrafo("Solo la parte por inversor responde al modo de fallo que se "
            "estudia: desconexion en bloque por hueco de tension. Colombia "
            "tiene 96,9 % por inversor, asi que a igual penetracion pierde "
            "mas MW de golpe.")
    if float(prod.sum()) < 1e-6:
        print()
        print(_c("   Este punto de operacion es NOCTURNO: el autoconsumo "
                 "solar no produce.", '93'))
        return
    print()
    print("   REPARTO POR REGION (MW produciendo)")
    reg = {}
    for b, mw in prod[prod > 0].items():
        r = region_de_bus(n.buses.at[b, 'x'], n.buses.at[b, 'y']) or 'resto'
        reg[r] = reg.get(r, 0.0) + float(mw)
    for r, mw in sorted(reg.items(), key=lambda kv: -kv[1]):
        print(f"      {r:18s} {mw:9.1f} MW   "
              f"({100*mw/float(prod.sum()):5.1f} %)")


def con_paises():
    n, _ = base()
    import pandas as pd
    print()
    print(f"   {'pais':>8} {'generacion':>12} {'demanda':>12} "
          f"{'neto':>12} {'buses':>7}")
    print("   " + "-" * 56)
    g = n.generators_t.p.iloc[0]
    c = n.loads_t.p.iloc[0]
    for p in ('ES', 'PT', 'FR'):
        bs = n.buses[n.buses.index.str.startswith(p)].index
        gg = float(g[n.generators[n.generators.bus.isin(bs)].index].sum())
        cc = float(c[n.loads[n.loads.bus.isin(bs)].index].sum())
        print(f"   {p:>8} {gg:9.1f} MW {cc:9.1f} MW {gg-cc:+9.1f} MW "
              f"{len(bs):7d}")
    print()
    parrafo("Francia son buses AGREGADOS (un generador por tecnologia = toda "
            "la flota francesa). No es un modelo de red: sirve de condicion "
            "de contorno y NO debe entrar en ninguna metrica del sistema "
            "iberico. Por eso la inercia y el deslastre excluyen Francia y "
            "si incluyen Portugal, que es la misma isla sincrona real.")


def con_cobertura():
    # Solo hace falta el Sistema (lee placa, despacho y tecnologia). Antes
    # llamaba tambien a base(), que no usaba, y eso costaba resolver el flujo
    # AC con el lazo de reactivo -minutos en la punta- para imprimir una
    # tabla.
    s = sistema()
    print()
    from iberia import dinamica_frecuencia as din
    filas = [
        ("topologia de la red", "DATO", "line_data.csv / bus_data.csv"),
        ("impedancias de linea", "DATO, validado",
         "contra la impedancia caracteristica Zc"),
        ("placa por generador", "DATO", "generation_data.csv"),
        ("despacho por tecnologia", "DERIVADO",
         "escalado uniforme, SIN orden de merito"),
        ("inercia H por maquina", "SUPUESTO",
         "por tecnologia; no hay fuente publica por unidad"),
        ("factor de carga acoplada", "SUPUESTO",
         f"FACTOR_CARGA_POR_CARRIER, {din.FACTOR_CARGA_UNIDAD} por defecto"),
        ("estatismo", "SUPUESTO",
         f"{din.ESTATISMO} uniforme, heredado de Colombia"),
        ("constante del gobernador", "SUPUESTO",
         f"{din.T_GOBERNADOR} s, heredada de Colombia, NO validada"),
        ("escalones del EDAC", "DATO", "P.O. 1.6, BOE"),
        ("BTM total", "DATO", "8.500 MW, reescalado a abril-2025"),
        ("reparto regional del BTM", "DERIVADO",
         "3 regiones conocidas + proporcional a la carga"),
        ("fraccion por inversor", "DERIVADO",
         "84,93 %, desglose NACIONAL, no por bus"),
        ("limites de reactivo", "SUPUESTO",
         "Qmax=sqrt(S^2-P^2), Qmin=-0,35 S"),
    ]
    for q, clase, nota in filas:
        col = {'DATO': '92', 'DERIVADO': '93', 'SUPUESTO': '93'}.get(
            clase.split(',')[0], '90')
        print(f"      {q:28s} " + _c(f"{clase:16s}", col) + f" {nota}")
    print()
    print(f"   Inercia resultante: Ek = {s.H*s.S_base/1000:.1f} GW.s "
          f"(H = {s.H:.3f} s)")
    print(_c("   SIN ANCLA EXTERNA: no hay cifra publicada de REE contra la "
             "que contrastarla.", '93'))


def con_escenarios():
    print()
    parrafo("Los tres puntos de operacion y de donde sale cada uno:")
    print()
    for clave, etq, aval, color in _ESCENARIOS:
        print(f"      {_c(clave, '1;96')}  {etq}")
        print(f"         {_c(aval, color)}")
    print()
    parrafo("El del APAGON se reconstruye en build_blackout_snapshot.py a "
            "partir de fuentes secundarias (NERC, prensa tecnica, informe de "
            "REE) y cierra su balance con una importacion neta de 200 MW que "
            "las fuentes no respaldan. El de PUNTA se deriva en "
            "build_punta_snapshot.py. El tercero es sintetico.")
    print()
    parrafo("El apagon es el escenario sobre el que descansan el BTM y el "
            "deslastre, y es el unico cuyo caso base N-1 esta limpio.")


# ---------------------------------------------------------------------------
# 3. Analisis
# ---------------------------------------------------------------------------

def ana_umbral():
    correr(['iberia.umbral_penetracion'] + _red())


def ana_sensibilidad():
    correr(['iberia.umbral_penetracion'] + _red() + ['--sensibilidad'])


def ana_lambda():
    op = elegir("que barrido", [
        'lambda en operacion NORMAL (el que fija el limite)',
        'calibracion completa de lambda  (~1 min)'])
    if op.startswith('lambda en'):
        correr(['iberia.barrido_lambda_normal'])
    else:
        correr(['iberia.calibrar_lambda_espana'])




# ---------------------------------------------------------------------------
# 4. Mapas
# ---------------------------------------------------------------------------

RAIZ = os.path.dirname(os.path.abspath(__file__))

# Los mapas del modelo: (ruta desde la raiz, que muestra, punto al que
# pertenece, modulo que lo genera). `None` = no es de ningun punto -es la
# red, o algo instalado- y vale para todos.
MAPAS = [
    ('resultados/mapas/mapa_red.png',
     'la red por nivel de tension, con los agregados de PT y FR', None,
     ['iberia.mapas', 'red']),
    ('resultados/mapas/mapa_carga_apagon.png',
     'cargabilidad de las ramas en el caso base', 'apagon',
     ['iberia.mapas', 'carga', '--red', 'apagon']),
    ('resultados/mapas/mapa_carga_punta.png',
     'cargabilidad de las ramas en el caso base', 'punta',
     ['iberia.mapas', 'carga', '--red', 'punta']),
    ('resultados/mapas/mapa_btm.png',
     'donde esta el BTM (placa instalada de autoconsumo)', None,
     ['iberia.mapas', 'btm']),
    ('resultados/visualizaciones/mapa_inercia.png',
     'inercia INSTALADA (H x placa) de la red de construccion', None,
     ['iberia.visualize_network']),
    ('resultados/visualizaciones/mapa_red_iberia.png',
     'la red sobre fondo cartografico', None,
     ['iberia.visualize_network']),
    ('resultados/visualizaciones/mapa_red_iberia_interactivo.html',
     'mapa interactivo, en el navegador (necesita internet)', None,
     ['iberia.visualize_network']),
]


def abrir(ruta):
    """Abre un fichero con la aplicacion que el sistema tenga por defecto.

    Con MENU_NO_ABRIR=1 en el entorno no abre nada y dice que habria
    abierto: es lo que permite comprobar el menu de forma automatica sin
    llenar la pantalla de ventanas."""
    if os.environ.get('MENU_NO_ABRIR'):
        print(_c(f"   (MENU_NO_ABRIR) se abriria: {ruta}", '90'))
        return True
    try:
        if sys.platform.startswith('win'):
            os.startfile(ruta)                                # noqa: S606
        else:
            orden = 'open' if sys.platform == 'darwin' else 'xdg-open'
            subprocess.Popen([orden, ruta], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        print(_c(f"   no se pudo abrir {ruta}: {e}", '91'))
        return False


def map_abrir():
    punto = _PUNTO['tipo']
    lista = [m for m in MAPAS if m[2] in (None, punto)]
    print()
    for i, (rel, desc, p, _) in enumerate(lista, 1):
        ruta = os.path.join(RAIZ, rel)
        de = 'de este punto' if p else 'del modelo'
        # La FECHA va siempre: un mapa sin fecha es un mapa del que no se
        # sabe si describe el modelo de hoy o uno anterior.
        if os.path.exists(ruta):
            estado = _c(time.strftime('%d-%b-%Y %H:%M', time.localtime(
                os.path.getmtime(ruta))), '90')
        else:
            estado = _c('todavia no generado', '93')
        print(f"     {_c(f'{i:2d}', '96')}) {desc}")
        print(f"         {_c(rel, '90')}  [{de}]  {estado}")
    if any(m[2] not in (None, punto) for m in MAPAS):
        print(_c("\n     (los mapas de carga de los otros puntos aparecen al "
                 "cambiar de punto con `p`)", '90'))
    print()
    sel = preguntar("numero, 't' para todos, o Enter para volver", "")
    if not sel:
        return
    if str(sel).strip().lower() in ('t', 'todos'):
        elegidos = lista
    else:
        try:
            elegidos = [lista[int(sel) - 1]]
        except (ValueError, IndexError):
            print(_c("   opcion no valida", '91'))
            return
    # Los que faltan se generan ANTES de abrir nada, y cada generador una
    # sola vez: visualize_network produce tres mapas de golpe.
    faltan = [m for m in elegidos if not os.path.exists(os.path.join(RAIZ, m[0]))]
    if faltan:
        print()
        for rel, *_ in faltan:
            print(f"      {rel}")
        if confirmar(f"{len(faltan)} mapa(s) no existen todavia. "
                     f"Generarlos ahora?"):
            hechos = []
            for _, _, _, gen in faltan:
                if gen not in hechos:
                    correr(gen)
                    hechos.append(gen)
    for rel, _, _, _ in elegidos:
        ruta = os.path.join(RAIZ, rel)
        if not os.path.exists(ruta):
            print(_c(f"   {rel}: no existe", '93'))
            continue
        if abrir(ruta):
            print(f"   abierto: {rel}")


def map_regenerar_carga():
    correr(['iberia.mapas', 'carga', '--red', _PUNTO['tipo']])


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
#
# Cada opcion declara SOBRE QUE corre: unas usan el punto de operacion
# elegido al entrar y otras son del modelo entero o de un escenario fijo
# (la validacion y lambda, sobre el apagon). Asi el menu dice siempre a que
# punto corresponde lo que muestra.
#
# Este menu es el de la copia PUBLICA: solo ofrece simular, consultar y
# analizar. Las pruebas y el mantenimiento (verificadores, estado del
# modelo, reconstruir la red, el proyecto por lotes) se ejecutan por linea
# de comandos (tests/ y tools/), no desde aqui.
#
#   sobre=PUNTO    la opcion corre sobre el punto elegido
#   sobre='texto'  NO depende del punto; el texto dice sobre que corre, y la
#                  opcion se pinta en el bloque "sobre el modelo entero"
#   no_aplica      {punto: razon}: en esos puntos la opcion no se ofrece, y
#                  el menu dice por que en vez de esconderla en silencio

PUNTO = None


def _op(grupo, nombre, accion, explica, sobre=PUNTO, no_aplica=None):
    return {'grupo': grupo, 'nombre': nombre, 'accion': accion,
            'explica': explica, 'sobre': sobre, 'no_aplica': no_aplica or {}}


_SIN_BTM_NOCHE = ("en la punta nocturna el BTM solar produce cero: el "
                  "umbral no esta definido")
_SOLO_APAGON = "se calcula sobre el apagon, el unico punto con medida real"

MENU = [
    # ======================= SOBRE ESTE PUNTO ============================
    _op('Simular', 'Simular contingencias (N-1)', sim_n1,
        "Saca de servicio lineas, transformadores y generadores y mide lo "
        "que la contingencia AÑADE sobre el caso base: sobrecargas nuevas, "
        "cuanto empeora la cargabilidad maxima y cuanta carga ESPANOLA queda "
        "aislada (los agregados de PT y FR no cuentan). La metrica es incremental a proposito: contada en "
        "absoluto, casi cualquier contingencia hereda las sobrecargas del "
        "caso base y sale 'con problemas' sin haber causado ninguno."),
    _op('Simular', 'Dinamica de frecuencia (P.O. 1.6)', sim_frecuencia,
        "Integra la ecuacion de oscilacion tras perder generacion de golpe y "
        "dispara los seis escalones del esquema espanol. Deja elegir si los "
        "dos escalones de BOMBEO actuan: sin ellos el esquema tiene la misma "
        "forma que el colombiano, que es como hay que correrlo para "
        "comparar."),
    _op('Simular', 'Deslastre con BTM: MILP frente al proporcional',
        sim_btm,
        "El algoritmo central del trabajo. Reparte generacion detras del "
        "contador por los buses, desconecta de golpe la parte conectada por "
        "inversor, resuelve un MILP que asigna buses a los escalones del "
        "P.O. 1.6 teniendo en cuenta cuanta generacion embebida SANA se "
        "llevaria cada corte, y lo COMPARA con el reparto proporcional "
        "ciego."),
    _op('Simular', 'Cascada BTM multironda', sim_cascada,
        "No supone que el sistema aguanta el primer golpe: encadena la "
        "caida de BTM con la perturbacion y deja correr la frecuencia hasta "
        "que el sistema se estabiliza o colapsa."),
    _op('Simular', 'Validacion contra la traza real del 28-A', sim_entsoe,
        "Alimenta el modelo con el evento real documentado y compara su "
        "frecuencia, segundo a segundo, con la que registro el Fraunhofer ISE "
        "en Malaga y publico NERC. Es la unica medida independiente contra la "
        "que se contrasta la dinamica.",
        no_aplica={'punta': "la traza medida es la del 28 de abril a las "
                            "12:33",
                   'escenario': "el escenario generico no es ningun "
                                "instante real"}),

    _op('Consultar', 'Resumen del sistema', con_resumen,
        "Las cifras de una ojeada: tamaño de la red, balance, tension, "
        "cargabilidad, inercia y mezcla por tecnologia. Avisa si el caso "
        "base arrastra generadores fuera de su curva de capacidad."),
    _op('Consultar', 'Buscar una barra, generador o linea', con_buscar,
        "Busca por texto libre y muestra lo que el modelo sabe: tension, "
        "generacion, carga, ramas conectadas con su flujo y cargabilidad. "
        "Marca los nudos RADIALES, que es donde se esconden los defectos de "
        "control de tension."),
    _op('Consultar', 'El BTM espanol', con_btm,
        "Placa instalada, factor de produccion derivado del propio "
        "snapshot, penetracion sobre la demanda y reparto por region. El "
        "84,93 % se conecta por inversor."),
    _op('Consultar', 'Balance por pais (ES / PT / FR)', con_paises,
        "Generacion, demanda e intercambio neto de cada pais, con el aviso "
        "de que Portugal y Francia son buses agregados."),
    _op('Consultar', 'Cobertura de datos: que es dato y que es supuesto',
        con_cobertura,
        "Que parametro es dato, cual derivado y cual supuesto. La diferencia "
        "con Colombia es grande: alli PARATEC publica inercia maquina a "
        "maquina; aqui no hay equivalente publico."),

    _op('Analizar', 'Umbral de penetracion con inversor', ana_umbral,
        "A partir de que penetracion una desconexion masiva de BTM llega a "
        "disparar el deslastre. Gemelo del analisis titular del STN. Informa "
        "el umbral de bombeo (49,5 Hz, propio de Espana) y el GENERAL "
        "(49,0 Hz), que es el comparable con Colombia.",
        no_aplica={'punta': _SIN_BTM_NOCHE}),
    _op('Analizar', 'Sensibilidad del umbral', ana_sensibilidad,
        "Cuanto se mueve el umbral si cambian los supuestos. La fila que "
        "importa es la ultima: SIN los dos escalones de bombeo, que es como "
        "esta armado el esquema colombiano.",
        no_aplica={'punta': _SIN_BTM_NOCHE}),
    _op('Analizar', 'Barrido del peso lambda', ana_lambda,
        "Recorre el peso de la penalizacion por destruir BTM sano. En "
        "Colombia este barrido tiene un precipicio; en Espana no, pero el "
        "efecto satura hacia lambda ~ 5.",
        no_aplica={'punta': _SOLO_APAGON, 'escenario': _SOLO_APAGON}),

    _op('Mapas', 'Abrir los mapas', map_abrir,
        "Abre los mapas con la aplicacion del sistema: los de este punto y "
        "los del modelo entero, cada uno con su FECHA. Si alguno no existe "
        "todavia -lo normal la primera vez-, ofrece generarlo en el momento."),
    _op('Mapas', 'Regenerar el mapa de carga de este punto',
        map_regenerar_carga,
        "Vuelve a dibujar la cargabilidad de las ramas de este punto. "
        "Resuelve el caso base con los limites de reactivo: ~1 min en el "
        "punto de operacion elegido.",
        no_aplica={'escenario': "no hay mapa de carga del escenario "
                                "generico"}),

    # ===================== SOBRE EL MODELO ENTERO ========================
    _op('Modelo', 'Comparar los dos escenarios lado a lado', sim_comparar,
        "Somete el apagon y la punta a las mismas pruebas y los imprime en "
        "columnas: balance, tensiones, cargabilidad, inercia, la misma "
        "perturbacion y una muestra de N-1.",
        sobre='apagon y punta'),
    _op('Modelo', 'Regenerar los mapas del modelo', sim_mapa,
        "Vuelve a dibujar los mapas que no dependen de un punto: la red, "
        "la red con fondo, el interactivo, la inercia instalada y el BTM.",
        sobre='la red, no un punto'),
    _op('Modelo', 'Como se construye cada escenario', con_escenarios,
        "De donde sale cada uno de los tres puntos de operacion y que aval "
        "tiene.",
        sobre='los tres puntos'),
]


def visibles():
    """(opciones de este punto, del modelo entero, ocultas con su razon)."""
    punto = _PUNTO['tipo']
    del_punto, del_modelo, ocultas = [], [], []
    for op in MENU:
        if punto in op['no_aplica']:
            ocultas.append((op['nombre'], op['no_aplica'][punto]))
        elif op['sobre'] is PUNTO:
            del_punto.append(op)
        else:
            del_modelo.append(op)
    return del_punto, del_modelo, ocultas


def numeradas():
    """Las opciones del punto activo en el orden en que se numeran."""
    dp, dm, _ = visibles()
    return dp + dm


def _nombre_de(accion):
    return next((op['nombre'] for op in MENU if op['accion'] is accion), '?')


def pintar_menu():
    titulo("MODELO IBERICO - ESPANA Y PORTUGAL")
    aval = next((a, c) for k, _, a, c in _ESCENARIOS if k == _PUNTO['tipo'])
    print()
    print(f"  {_c('PUNTO DE OPERACION:', '1;96')} "
          f"{_c(_PUNTO['etiqueta'], '1;97')}")
    print(f"  {_c(aval[0], aval[1])}")
    dp, dm, ocultas = visibles()

    i = 0
    print()
    print(_c(f"  SOBRE ESTE PUNTO DE OPERACION", '1;93')
          + _c(f"  ({_PUNTO['tipo']})", '93'))
    grupo = None
    for op in dp:
        if op['grupo'] != grupo:
            grupo = op['grupo']
            print(_c(f"   {grupo}", '1'))
        i += 1
        print(f"    {_c(f'{i:2d}', '96')}) {op['nombre']}")

    print()
    print(_c("  SOBRE EL MODELO ENTERO", '1;93')
          + _c("  (no cambia con el punto elegido)", '90'))
    for op in dm:
        i += 1
        print(f"    {_c(f'{i:2d}', '96')}) {op['nombre']:<42s}"
              + _c(op['sobre'], '90'))

    if ocultas:
        print()
        print(_c("  No se ofrecen en este punto:", '90'))
        for nombre, razon in ocultas:
            print(_c(f"     - {nombre}: {razon}", '90'))
    print()
    print(f"    {_c(' p', '96')}) cambiar el punto de operacion")
    print(f"    {_c(' q', '96')}) salir")
    if any(k[0] == 'lim' for k in _BASE):
        print(_c("\n   (caso en memoria: las consultas son inmediatas)", '90'))


def main():
    try:
        import pypsa  # noqa: F401
    except ImportError:
        print("\n   Faltan las dependencias del modelo. Desde esta carpeta:\n")
        print("      pip install -r requirements.txt\n")
        return 1
    # `python -m iberia...` necesita que el directorio de trabajo sea la raiz
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    import logging
    logging.disable(logging.INFO)

    # Lo primero es sobre QUE sistema se trabaja, no que analisis se corre.
    if elegir_punto(primera_vez=True) is None:
        return 0

    while True:
        pintar_menu()
        acciones = numeradas()
        try:
            sel = input(_c("\n   opcion: ", '96')).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if sel in ('q', 'salir', 'exit'):
            print(_c("\n   hasta luego\n", '90'))
            return 0
        if sel in ('p', 'punto'):
            titulo("CAMBIAR EL PUNTO DE OPERACION")
            print()
            if elegir_punto():
                print(_c("\n   punto cambiado; el caso en memoria se "
                         "descarto", '90'))
            pausa()
            continue
        if not sel:
            # un Enter de mas no debe cerrar la sesion: tirarla cuesta
            # reconstruir el caso base cacheado (~1 min).
            continue
        if not sel.isdigit() or not (1 <= int(sel) <= len(acciones)):
            print(_c("   opcion no valida", '91'))
            continue

        op = acciones[int(sel) - 1]
        titulo(op['nombre'].upper())
        # Sobre que corre, SIEMPRE, antes de correr: es lo que el menu
        # anterior no decia y por lo que parecia ignorar el punto elegido.
        sobre = (_PUNTO['etiqueta'] if op['sobre'] is PUNTO
                 else op['sobre'] + '  (no depende del punto elegido)')
        print(_c(f"   corre sobre: {sobre}", '90'))
        print()
        parrafo(op['explica'])
        try:
            op['accion']()
        except KeyboardInterrupt:
            print(_c("\n   interrumpido", '93'))
        except Exception as e:                               # noqa: BLE001
            print(_c(f"\n   ERROR: {type(e).__name__}: {e}", '91'))
            import traceback
            traceback.print_exc(limit=3)
        pausa()


if __name__ == '__main__':
    sys.exit(main())
