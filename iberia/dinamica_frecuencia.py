"""Dinamica de frecuencia tras una perturbacion, adaptada de
stn/agc_deslastre.py del modelo del STN colombiano (modelo de una sola masa: respuesta inercial,
regulacion primaria por estatismo, amortiguamiento de la carga).

A diferencia del STN, aqui NO se modela el EDAC (deslastre automatico por
baja frecuencia) ni el AGC - este modulo responde solo "que le pasa a la
frecuencia mientras el BTM se cae", no "cual seria la respuesta correcta
despues". Ver 06_documentacion/2026-09-27-diseno-sub-proyecto-D-btm.md.

Los generadores de este modelo ya traen H por unidad individual (no hay que
cruzar con un registro externo como PARATEC), asi que 's_sinc' es mas simple
que en Colombia: un generador esta "girando" si su p_set es una fraccion no
trivial de su p_nom (esta ya despachado en el punto de operacion), no hace
falta calcular cuantas maquinas de una planta multi-unidad estan acopladas."""
import numpy as np

F0 = 50.0                # Hz, frecuencia nominal europea (Colombia usa 60)
ESTATISMO = 0.05          # 5%, mismo valor que el STN - no hay dato real
                           # de estatismo por maquina para España
AMORTIGUAMIENTO = 1.5      # % carga por % frecuencia, igual que el STN
RESERVA_PRIMARIA = 0.10    # fraccion de la capacidad girando disponible

# --- Regulacion primaria: el modelo de respuesta de frecuencia estandar --
#
# CORREGIDO EL 4-NOV-2026. Hasta entonces la primaria era un UNICO retardo
# de primer orden de 8 s, heredado del modelo colombiano y marcado como no
# validado. Le faltaba la parte de la turbina que responde al instante, y
# eso la hacia llegar tarde: ante 3.000 MW en la punta el nadir rozaba
# 49,000 Hz -el umbral del primer escalon del P.O. 1.6- por milesimas,
# disparaba 6.010 MW de golpe y la frecuencia subia a 51,46 Hz.
#
# Ahora se usa el modelo de respuesta de frecuencia de Anderson y Mirheydar
# (IEEE Trans. Power Syst. 5(3):720-729, 1990): una turbina con
# recalentamiento, en la que la fraccion de alta presion F_H responde casi
# de inmediato y el resto llega con la constante de recalentamiento T_R.
# Valores TIPICOS del articulo, no ajustados a ninguna medida de este
# modelo: F_H = 0,3 y T_R = 8 s. Es decir, los 8 s no estaban mal; faltaba
# la fraccion inmediata.
#
# Contraste con la traza del 28-A (validar_traza_28a.py): la caida total
# pasa de 0,973 a 0,776 Hz frente a 0,750 medidos, y el error medio de 0,207
# a 0,105 Hz. Pero esa traza es la de Europa continental entera hasta la
# separacion de Francia, y el modelo es una Iberia aislada: es un indicio
# COHERENTE con el cambio, no una validacion del regulador. El cambio se
# sostiene por la literatura.
F_H_ALTA_PRESION = 0.3     # fraccion de respuesta inmediata
T_GOBERNADOR = 8.0         # s, constante de recalentamiento T_R

# --- Regulacion secundaria (AGC) ------------------------------------------
#
# Sin ella la frecuencia nunca vuelve a 50 Hz: la primaria la deja en el
# error de estatismo, que es su comportamiento correcto. MISMO esquema que
# el modelo del STN colombiano (stn/agc_deslastre.py), a proposito, para que los
# dos modelos se puedan comparar:
#
#     d(dP_agc)/dt = -(1/T_AGC) * B * (f - f0),   B = P_gen/R + D*P_carga
#
# con B la caracteristica natural del sistema en MW/Hz, y la reserva
# COMPARTIDA con la primaria (se acota la suma, no cada una por su lado).
#
# EL RETARDO NO ES UN DETALLE. La secundaria no actua hasta 30 s despues de
# la primera perturbacion: el nadir y los escalones del P.O. 1.6 ocurren en
# los primeros segundos, y un AGC que arrancara antes haria parecer al
# sistema mas robusto justo en lo que mide este trabajo. Con el retardo, el
# AGC no cambia ni el nadir ni el deslastre (verificar_respuesta_frecuencia).
T_AGC = 30.0               # s, constante de tiempo del lazo secundario
T_AGC_RETARDO = 30.0       # s desde la perturbacion hasta que actua

# --- Reduccion de generacion por sobrefrecuencia (LFSM-O) -----------------
#
# El Reglamento (UE) 2016/631 (NC RfG, art. 13.2) exige a TODA la
# generacion que reduzca su produccion cuando la frecuencia supera un
# umbral de 50,2 Hz, con un estatismo entre el 2 y el 12 % (5 % por
# defecto). Sin ella, un deslastre que corta mas de lo que falta no lo
# frena nadie: era la otra mitad de la joroba de 51,46 Hz. No sale de la
# reserva de la primaria: es una reduccion de la produccion.
F_LFSM_O = 50.2            # Hz, umbral
ESTATISMO_LFSM_O = 0.05    # 5 %
T_LFSM_O = 2.0             # s, retardo de la respuesta

# Carga a la que opera una unidad ACOPLADA. Sirve para deducir cuanta
# capacidad esta de verdad sincronizada a partir de la potencia
# despachada: s_acoplada = |p_set| / factor, topada en p_nom.
# Justificacion en Sistema.__init__.
#
# Valor por defecto, para las tecnologias que no aparecen en
# FACTOR_CARGA_POR_CARRIER y para Portugal (no hay desglose de su
# despacho por tecnologia en este modelo).
FACTOR_CARGA_UNIDAD = 0.70

# EL FACTOR NO ES UNICO: depende del PAPEL OPERATIVO de la tecnologia.
#
# Un unico 0,70 para todo el parque es falso en los dos extremos. Una
# central nuclear es base: va a su potencia nominal y no presta
# regulacion primaria, asi que suponerle un 30% de margen le inventa
# capacidad girando. Una bomba de velocidad fija no modula: consume su
# nominal o esta parada. En el otro sentido, la hidraulica de embalse es
# justo la que SI guarda margen -es el regulador del sistema- y opera
# bastante por debajo de su placa.
#
# Cada valor sale del papel de la maquina, no de cuadrar ninguna cifra
# agregada. El efecto neto sobre la energia cinetica es un RESULTADO
# (ver la nota de Sistema.__init__), no el objetivo.
FACTOR_CARGA_POR_CARRIER = {
    'Nuclear':        0.98,  # base: a plena carga, sin reserva primaria
    'Pumped_storage': 0.95,  # bomba de velocidad fija: no modula
    'Coal':           0.75,  # termica de base con algo de margen
    'Steam_turbine':  0.75,
    'Biomass':        0.80,  # opera como base, margen pequeno
    'Combined_cycle': 0.70,  # carga parcial, reserva + seguimiento
    'Gas_turbine':    0.70,
    'ICCC':           0.70,
    'Run_of_river':   0.70,  # fluyente: lo que trae el rio, no modula mucho
    'Reservoir':      0.55,  # el regulador del sistema: margen arriba Y abajo
}
BANDA_MUERTA_HZ = 0.030    # igual orden de magnitud que el STN
F_COLAPSO = 47.5           # Hz - mismos 2,5 Hz de desviacion absoluta que el
                           # F_COLAPSO=57.5 del STN (60-57.5=2,5; 50-2,5=47,5)
DT = 0.01
T_FIN = 60.0

# Tecnologias tras convertidor: ni inercia ni regulacion primaria (mismo
# criterio que TIPOS_CONVERTIDOR del STN, adaptado a los nombres de carrier
# de este modelo).
CARRIERS_CONVERTIDOR = ('PV', 'Onshore', 'Offshore_floating', 'Solar Thermal')

# Escalones de deslastre automatico por minima frecuencia, P.O. 1.6 de REE
# (BOE-A-1998-20053, resolucion original de 1998, y su adaptacion
# BOE-A-2009-8813 de 2009 - las dos fuentes dan la misma tabla, verificado
# de forma independiente). Estos son los 4 escalones GENERALES, que actuan
# sobre demanda de clientes; los dos de BOMBEO estan mas abajo
# (EDAC_UMBRALES_BOMBEO_ESPANA) y disparan antes.
#
# BUSQUEDA EXHAUSTIVA DE LA TEMPORIZACION POR ESCALON: se consultaron las
# dos resoluciones del BOE citadas, los "Criterios Generales de Proteccion
# del Sistema Electrico Espanol" de REE (version consolidada y version de
# 2017), los criterios de 1995, y un paper especializado en esquemas de
# deslastre (IIT Comillas). NINGUNA fuente publica un retardo por escalon
# para el sistema peninsular (a diferencia del Acuerdo 2105 colombiano,
# que si detalla 200-4000 ms). El unico tiempo que aparece en el texto
# legal es un piso de COORDINACION de las protecciones de los propios
# generadores ("solo podran desacoplar si la frecuencia cae por debajo de
# 48 Hz, temporizado con tres segundos, como minimo"), que no es el
# retardo del rele de deslastre. Se usa disparo INMEDIATO al cruzar el
# umbral, documentado como simplificacion.
EDAC_UMBRALES_HZ_ESPANA = (49.0, 48.7, 48.4, 48.0)
EDAC_FRACCION_ESPANA = (0.15, 0.15, 0.10, 0.10)

# ESCALONES DE BOMBEO del mismo P.O. 1.6: 49,5 y 49,3 Hz, el 50% de los
# grupos de bombeo en cada uno.
#
# Disparan ANTES que los cuatro generales (49,5 > 49,0), que es
# precisamente su razon de ser: desconectar bombeo es deslastre
# indoloro -nadie se queda sin luz- asi que el esquema lo gasta primero
# y reserva el deslastre de clientes para cuando aquello no basta.
#
# POR QUE NO ESTABAN IMPLEMENTADOS, y por que ahora si: el codigo decia
# que "iberia_blackout.nc no tiene carga de bombeo activa en este punto
# de operacion (Pumped_storage esta despachado como generacion)". Eso
# era consecuencia de un ERROR DE DATOS: el bombeo estaba con el signo
# cambiado. La lamina 4 del informe de NERC documenta "Pumped Storage
# 3GW consume" para el instante del apagon. Corregido el signo, hay
# 3.000 MW de bombeo que el esquema real habria desconectado.
EDAC_UMBRALES_BOMBEO_ESPANA = (49.5, 49.3)
EDAC_FRACCION_BOMBEO_ESPANA = (0.50, 0.50)


def describir(traza):
    """Describe el desenlace con la variable que SI informa en cada caso.

    Si el sistema colapsa no hay nadir -la trayectoria se corta al cruzar
    F_COLAPSO, donde este modelo de una sola masa deja de ser valido- y lo
    que discrimina entre escenarios es el INSTANTE del cruce. Si no
    colapsa, el nadir es un minimo real y es lo que se cita.

    Existe porque antes cada script imprimia `nadir` en los dos casos, y
    como casi todos los escenarios colapsan salia siempre ~47,5 Hz: una
    columna entera que parecia decir "el sistema se queda siempre al
    borde" cuando decia "aqui cortamos la integracion"."""
    if traza['colapso']:
        return f"COLAPSA en t={traza['t_colapso']:.2f} s"
    return (f"sobrevive | nadir={traza['nadir']:.3f} Hz "
            f"en t={traza['t_nadir']:.2f} s")


class Sistema:
    """Parametros agregados que gobiernan la respuesta de frecuencia."""

    def __init__(self, network, umbral_girando_pct=0.01):
        self.network = network
        # Francia es una proxy pais-nivel de 4 buses ficticios (un generador
        # por tecnologia = TODA la flota francesa de esa tecnologia), no un
        # modelo real de area sincrona - se excluye de la inercia/demanda
        # agregada que representa este Sistema. Portugal se mantiene: es la
        # misma isla sincrona iberica real que España (AC directo, misma
        # zona de frecuencia).
        iberia_buses = network.buses[network.buses.index.str.startswith(('ES', 'PT'))].index
        gen = network.generators[network.generators.bus.isin(iberia_buses)].copy()

        # CAPACIDAD ACOPLADA, no placa entera.
        #
        # Antes: `s_sinc = p_nom` para toda maquina despachada por encima
        # del 1% de su placa. Eso supone que esta sincronizado el parque
        # NOMINAL integro - la nuclear aportaba 7.408 MVA girando mientras
        # producia 3.400 MW. El modelo salia con 137,2 GW.s de energia
        # cinetica (4,31 s sobre la demanda) frente a los ~2,3 s que REE
        # declaro para ese instante: casi el DOBLE de inercia que la real.
        #
        # El origen del defecto no es la formula sino el despacho:
        # fix_balearic.py reparte la generacion de forma uniforme sobre
        # toda la flota (todos los no-renovables espanoles al 20,91% exacto
        # de su placa), asi que las centrales que en realidad estarian
        # PARADAS aparecen acopladas a baja carga y aportan una inercia que
        # no existe. Es el mismo defecto de compromiso de unidades que ya
        # se habia diagnosticado en el modelo colombiano.
        #
        # Criterio: una central acopla las unidades que necesita para su
        # despacho, y esas unidades operan al factor de carga propio de su
        # tecnologia (FACTOR_CARGA_POR_CARRIER, 0,70 por defecto). El
        # resto del parque esta parado y no gira.
        #
        # ATENCION, AQUI HUBO UNA VALIDACION FALSA (retirada 10-oct-2026).
        #
        # Este bloque contenia un barrido de calibracion del factor
        # -0,60 / 0,70 / 0,80 / 0,90- cuya fila adoptada, 0,70, daba
        # 72,4 GW.s = 2,28 s, junto a la linea "REE declaro ~2,3 s", y
        # concluia que la coincidencia era una validacion independiente.
        # Las dos mitades eran falsas:
        #
        #  1. LOS "~2,3 s DE REE" NO EXISTEN. No estan en el informe de
        #     REE del 18-jun-2025 (que ademas sostiene que el incidente NO
        #     fue un problema de inercia, sino de tension), ni en las
        #     laminas de NERC, ni en ninguna de las fuentes secundarias
        #     que el proyecto cita. La cifra entro sin referencia y se uso
        #     como ancla durante cuatro sub-proyectos.
        #  2. LOS 72,4 GW.s ERAN UN ERROR DE DATOS. Al corregir el resto
        #     termico (estaba aplastado al 1% = ~62 MW; NERC documenta
        #     3.000 MW) la Ek sube a 93,8 GW.s. Medido deshaciendo cada
        #     correccion por separado: solo-termico 93,8 -> 72,0;
        #     solo-bombeo 93,8 -> 93,8 (el signo del bombeo es EXACTAMENTE
        #     neutro para la inercia, ver mas abajo). Es decir: la
        #     coincidencia con la cifra sin fuente la producia el bug.
        #
        # Tampoco sirve la traza de frecuencia de Fraunhofer (lamina 7 de
        # NERC) para acotar esto: el RoCoF medido implica 127-676 GW.s,
        # el rango de TODA el area sincrona de Europa continental, porque
        # hasta las 12:33:21 la interconexion AC con Francia seguia
        # cerrada. Ninguna medida anterior a la separacion puede validar
        # la inercia de una Iberia aislada, que es lo que modela esta
        # clase. NO HAY, a dia de hoy, ancla externa para esta cifra.
        #
        # Por eso los factores se justifican uno a uno por el papel
        # operativo de la maquina (ver FACTOR_CARGA_POR_CARRIER) y no por
        # el agregado que producen. Efecto neto de pasar del 0,70
        # uniforme a los factores por tecnologia, para que quede medido:
        #
        #   0,70 uniforme        93,8 GW.s   (2,95 s sobre demanda ES+PT)
        #   por tecnologia       85,5 GW.s   (2,69 s)
        #     nuclear  -8,3 | bombeo  -4,5 | embalse  +4,7 | resto  -0,2
        #
        # Efecto secundario util: con este criterio el umbral del 1% deja
        # de ser un filo de cuchillo. Antes, una maquina al 1,1% de su
        # placa aportaba su placa ENTERA y una al 0,9% aportaba cero;
        # ahora aporta |p_set|/factor en los dos casos, de forma continua.
        # Se usa el VALOR ABSOLUTO de p_set: una maquina que BOMBEA esta
        # igual de sincronizada que una que genera. Su motor gira a
        # velocidad sincrona y su masa aporta la misma energia cinetica;
        # lo unico que cambia es el sentido del flujo de potencia.
        #
        # Importa desde que el bombeo se despacha como consumo (p_set
        # negativo, ver build_blackout_snapshot): con `p_set` a secas,
        # `girando` daba False y esos 3 GW de maquina rotante aportaban
        # CERO inercia, que es justo lo contrario de la fisica.
        p_abs = gen.p_set.abs()
        girando = p_abs >= (umbral_girando_pct * gen.p_nom.clip(lower=1e-9))
        factor = gen.carrier.map(FACTOR_CARGA_POR_CARRIER).fillna(
            FACTOR_CARGA_UNIDAD)
        acoplada = np.minimum(gen.p_nom, p_abs / factor)
        gen['s_sinc'] = acoplada.where(girando, 0.0)
        self.gen = gen
        self.s_sinc = gen['s_sinc']

        self.P_gen = float(gen.p_set.sum())
        self.P_carga = float(network.loads[network.loads.bus.isin(iberia_buses)].p_set.sum())

        # Carga ESPANOLA sola. El P.O. 1.6 es el esquema de REE y sus
        # releses abren alimentadores espanoles: no puede deslastrar
        # demanda portuguesa, aunque PT este en la misma isla sincrona.
        #
        # Antes los escalones se calculaban sobre self.P_carga (ES+PT), lo
        # que metia ~2.400 MW de carga portuguesa en el plan - MW que
        # ningun rele espanol puede abrir. Eso inflaba artificialmente la
        # capacidad del esquema y es lo que sostenia el "limite de
        # supervivencia del 61-62%".
        #
        # P_carga sigue siendo ES+PT y eso es CORRECTO para la ecuacion de
        # oscilacion: toda la isla sincrona aporta amortiguamiento de
        # carga. Son dos bases distintas para dos cosas distintas.
        buses_es = network.buses[network.buses.index.str.startswith('ES')].index
        self.P_carga_es = float(
            network.loads[network.loads.bus.isin(buses_es)].p_set.sum())
        # Excedente de regimen permanente que sale de Iberia por el
        # interconector con Francia (y residuo no asignado, ver Tarea 1):
        # un flujo constante, ya equilibrado, que la ecuacion de oscilacion
        # no debe confundir con una perturbacion.
        # BOMBEO ESPANOL EN CONSUMO, en MW positivos.
        #
        # Esta modelado como generacion NEGATIVA (ver
        # build_blackout_snapshot), asi que no aparece en P_carga ni en
        # P_carga_es: hay que sacarlo aparte para que los escalones de
        # bombeo del P.O. 1.6 sepan sobre que base actuan.
        #
        # Desconectarlo es deslastre: al soltar la bomba, esos MW dejan
        # de consumirse y el desbalance mejora en la misma cantidad.
        bombeo = gen[(gen.carrier == 'Pumped_storage') & (gen.p_set < 0)]
        self.P_bombeo_es = float(-bombeo[
            bombeo.bus.isin(buses_es)].p_set.sum())

        self.exportacion = self.P_gen - self.P_carga
        self.S_base = float(self.s_sinc.sum())

        # H equivalente, ponderado por capacidad girando. Cada generador ya
        # trae su H propio (hotfix del sub-proyecto A) - no hace falta
        # mapear por tecnologia como hace el STN cuando no hay dato real.
        self.H = float((gen.H * self.s_sinc).sum() / max(self.S_base, 1e-9))

        # Estatismo equivalente: sin dato real por maquina para España, se
        # usa el valor por defecto uniforme (misma limitacion que la mayoria
        # de las maquinas del STN, que tampoco tienen dato real).
        self.R_eq = ESTATISMO

        # Reserva primaria: excluye tecnologias tras convertidor, igual
        # justificacion que el STN (CREG 060 art.12 en Colombia; España
        # tiene una exencion equivalente en sus procedimientos de operacion
        # para renovables no gestionables).
        es_convertidor = gen.carrier.isin(CARRIERS_CONVERTIDOR)
        margen = (self.s_sinc - gen.p_set).clip(lower=0.0)
        res = np.minimum(margen, self.s_sinc * RESERVA_PRIMARIA)
        res = res.where(~es_convertidor, 0.0)
        self.reserva = float(res.sum())

        baja = np.minimum(self.s_sinc * RESERVA_PRIMARIA, gen.p_set.clip(lower=0.0))
        baja = baja.where(~es_convertidor, 0.0)
        self.reserva_baja = float(baja.sum())

    def resumen(self):
        print(f"  generacion despachada : {self.P_gen:9.1f} MW")
        print(f"  demanda               : {self.P_carga:9.1f} MW")
        print(f"  capacidad girando     : {self.S_base:9.1f} MVA")
        print(f"  inercia equivalente H : {self.H:9.2f} s")
        print(f"  estatismo equivalente : {self.R_eq:9.4f}")
        print(f"  reserva primaria      : {self.reserva:9.1f} MW "
              f"({100*self.reserva/max(self.P_gen,1e-9):.1f}% del despacho)")


def simular_frecuencia(sis, eventos, con_deslastre=False,
                       umbrales_bombeo=EDAC_UMBRALES_BOMBEO_ESPANA,
                       fracciones_bombeo=EDAC_FRACCION_BOMBEO_ESPANA,
                       umbrales=EDAC_UMBRALES_HZ_ESPANA,
                       fracciones=EDAC_FRACCION_ESPANA,
                       con_agc=True, con_lfsm=True, t_fin=None):
    """Integra la ecuacion de oscilacion tras una serie de perturbaciones.

    `eventos` es una lista de dicts {'t': segundos, 'dP_gen': MW perdidos
    (positivo = se pierde generacion), 'dP_carga': MW que aparecen como mas
    demanda (asi es como entra el BTM: el operador no lo ve desaparecer, lo
    ve aparecer como mas carga), 'etiqueta': texto}.

    `con_deslastre` activa el esquema real espanol de deslastre automatico
    por minima frecuencia (P.O. 1.6, ver EDAC_UMBRALES_HZ_ESPANA arriba):
    cada escalon dispara SIN retardo en cuanto la frecuencia cruza su
    umbral, cortando `fraccion` de la carga VIGENTE en ese instante (no la
    inicial - si ya se sumo carga por BTM caido, el escalon corta sobre esa
    carga inflada, igual que mide un rele real). Por defecto esta
    desactivado: el comportamiento de quien no lo pide (D4 incluido) es
    identico a antes de este cambio.

    `con_agc` y `con_lfsm` activan la regulacion secundaria y la reduccion
    por sobrefrecuencia (ver las constantes de arriba). Los dos estan
    activados por defecto, porque son parte de un sistema real; se pueden
    apagar para aislar su efecto. `t_fin` alarga la integracion (por
    defecto T_FIN): para ver la vuelta a 50 Hz hacen falta un par de
    minutos.

    Devuelve (t, f, traza) - sin reparto por bus: eso lo decide el MILP de
    deslastre_btm_espana.py (E2/E4) a partir de traza['escalones'].
    """
    ev = sorted(eventos, key=lambda e: float(e.get('t', 0.0)))
    for e in ev:
        e.setdefault('dP_gen', 0.0)
        e.setdefault('dP_carga', 0.0)
        e['aplicado'] = False

    n = int((T_FIN if t_fin is None else float(t_fin)) / DT)
    t = np.arange(n) * DT
    f = np.zeros(n)
    f[0] = F0

    P_gen = sis.P_gen
    P_carga = sis.P_carga
    P_carga_es = sis.P_carga_es
    reserva = sis.reserva
    reserva_baja = sis.reserva_baja

    a_gob = float(np.exp(-DT / T_GOBERNADOR))
    dP_prim = 0.0
    x_recal = 0.0       # estado de la parte de recalentamiento de la turbina
    dP_agc = 0.0        # aporte acumulado de la regulacion secundaria
    dP_lfsm = 0.0       # reduccion por sobrefrecuencia (negativa)
    a_lfsm = float(np.exp(-DT / T_LFSM_O))
    t_agc_desde = (min(float(e.get('t', 0.0)) for e in ev) if ev else 0.0) \
        + T_AGC_RETARDO
    carga_deslastrada = 0.0

    escalones = ([{'umbral': u, 'fraccion': fr, 'disparado': False,
                  't_disparo': None, 'mw': 0.0}
                 for u, fr in zip(umbrales, fracciones)]
                if con_deslastre else [])

    # Escalones de BOMBEO: disparan antes y actuan sobre el bombeo, no
    # sobre la demanda de clientes. Se llevan aparte porque su base es
    # otra y porque interesa poder reportarlos por separado: son
    # deslastre indoloro.
    # getattr con 0.0 por defecto: los sistemas sinteticos de los tests
    # no modelan bombeo, y un escenario sin bombeo en consumo tampoco
    # tiene nada que soltar. En los dos casos estos escalones son inertes.
    P_bombeo = float(getattr(sis, 'P_bombeo_es', 0.0))
    escalones_bombeo = ([{'umbral': u, 'fraccion': fr, 'disparado': False,
                          't_disparo': None, 'mw': 0.0}
                         for u, fr in zip(umbrales_bombeo, fracciones_bombeo)]
                        if (con_deslastre and P_bombeo > 0) else [])

    for e in ev:
        if float(e['t']) <= 0.0:
            P_gen -= float(e['dP_gen'])
            P_carga += float(e['dP_carga'])
            P_carga_es += float(e['dP_carga'])
            e['aplicado'] = True

    colapso = False
    bombeo_deslastrado = 0.0
    for k in range(1, n):
        for e in ev:
            if not e['aplicado'] and float(e['t']) <= t[k]:
                P_gen -= float(e['dP_gen'])
                P_carga += float(e['dP_carga'])
                P_carga_es += float(e['dP_carga'])
                e['aplicado'] = True
                e['t_real'] = float(t[k])

        df_pu = (f[k - 1] - F0) / F0
        bm = BANDA_MUERTA_HZ / F0
        df_util = (df_pu + bm) if df_pu < -bm else (
            (df_pu - bm) if df_pu > bm else 0.0)
        objetivo = -df_util / sis.R_eq * sis.P_gen
        objetivo = max(-reserva_baja, min(objetivo, reserva))
        # Turbina de recalentamiento (Anderson-Mirheydar): la fraccion de
        # alta presion sigue al objetivo al instante; el resto, con T_R.
        x_recal = objetivo + (x_recal - objetivo) * a_gob
        dP_prim = F_H_ALTA_PRESION * objetivo \
            + (1.0 - F_H_ALTA_PRESION) * x_recal

        # Secundaria: integrador puro sobre el error de frecuencia, a partir
        # de T_AGC_RETARDO tras la primera perturbacion.
        if con_agc and t[k] >= t_agc_desde:
            B = (sis.P_gen / sis.R_eq + AMORTIGUAMIENTO * P_carga) / F0
            dP_agc -= (DT / T_AGC) * B * (f[k - 1] - F0)
        # La reserva es UNA y la comparten los dos lazos.
        aporte = dP_prim + dP_agc
        if aporte > reserva:
            dP_agc = reserva - dP_prim
        elif aporte < -reserva_baja:
            dP_agc = -reserva_baja - dP_prim

        # LFSM-O: por encima de 50,2 Hz toda la generacion reduce.
        if con_lfsm:
            exceso = max(0.0, (f[k - 1] - F_LFSM_O) / F0)
            obj_lfsm = -exceso / ESTATISMO_LFSM_O * sis.P_gen
            dP_lfsm = obj_lfsm + (dP_lfsm - obj_lfsm) * a_lfsm

        # Se descuenta carga_deslastrada ademas de sis.exportacion (ver
        # Sistema.__init__ en D2): la carga efectiva es la que queda tras
        # los escalones que ya dispararon.
        carga_efectiva = (P_carga - carga_deslastrada) * (
            1.0 + AMORTIGUAMIENTO * df_pu)
        desbalance = (P_gen + dP_prim + dP_agc + dP_lfsm) - carga_efectiva \
            - sis.exportacion
        df_dt = desbalance / (2.0 * sis.H * max(sis.S_base, 1e-9)) * F0
        f[k] = f[k - 1] + df_dt * DT

        # BOMBEO primero: sus umbrales (49,5/49,3) son mas altos que los
        # generales (49,0...48,0), asi que en una bajada se cruzan antes.
        for esc in escalones_bombeo:
            if not esc['disparado'] and f[k] <= esc['umbral']:
                esc['disparado'] = True
                esc['t_disparo'] = float(t[k])
                esc['mw'] = P_bombeo * esc['fraccion']
                # Soltar la bomba hace que esos MW dejen de consumirse:
                # el desbalance mejora. Como el bombeo esta modelado como
                # generacion negativa, equivale a subir P_gen.
                P_gen += esc['mw']
                bombeo_deslastrado += esc['mw']

        for esc in escalones:
            if not esc['disparado'] and f[k] <= esc['umbral']:
                esc['disparado'] = True
                esc['t_disparo'] = float(t[k])
                # Base ESPANOLA, e inflada por el BTM caido. Las dos
                # cosas, y por razones distintas:
                #
                # - ESPANOLA porque el P.O. 1.6 es el esquema de REE: sus
                #   releses no pueden abrir alimentadores portugueses.
                #   Usar ES+PT metia ~2.400 MW que nadie puede deslastrar.
                #
                # - INFLADA porque el esquema se ARMA sobre demanda neta
                #   prevista (15% de los alimentadores), pero al disparar
                #   esos alimentadores sueltan la carga BRUTA que hay
                #   detras. Si el BTM se ha caido, detras hay mas MW de
                #   los que decia la etiqueta. Dimensionar y entregar no
                #   son lo mismo.
                #
                # SUPUESTO DECLARADO: se atribuye todo el incremento de
                # carga (dP_carga) a Espana, porque en este modelo el BTM
                # solo esta mapeado a buses espanoles (btm_regional.py).
                # Si algun escenario futuro mete dP_carga portuguesa, hay
                # que separarlo aqui.
                esc['mw'] = P_carga_es * esc['fraccion']
                carga_deslastrada += esc['mw']

        if f[k] < F_COLAPSO:
            t = t[:k + 1]
            f = f[:k + 1]
            colapso = True
            break

    # NADIR: solo existe si la trayectoria SE RECUPERA.
    #
    # Antes se reportaba `f.min()` siempre, y cuando habia colapso eso era
    # la primera muestra por debajo de F_COLAPSO - es decir, el
    # truncamiento, no un minimo. El sintoma: las 11 filas del barrido de
    # sensibilidad cabian en 0,0153 Hz, todas pegadas a 47,5. Esa columna
    # no contenia informacion; parecia "el sistema siempre se queda a un
    # pelo del limite" cuando en realidad decia "aqui cortamos".
    #
    # Tampoco vale seguir integrando hasta que la curva se aplane: el
    # modelo es de una sola masa y NO representa el disparo de generacion
    # por subfrecuencia, asi que su "estado estacionario" de ~35 Hz es
    # igual de ficticio. Por debajo de F_COLAPSO el modelo deja de ser
    # valido, y punto.
    #
    # Asi que: si colapsa, nadir y t_nadir son NaN y la variable
    # informativa es t_colapso. Si no colapsa, el nadir es real y citable.
    if colapso:
        nadir, t_nadir = float('nan'), float('nan')
        t_colapso = float(t[-1])
    else:
        nadir = float(f.min())
        t_nadir = float(t[int(np.argmin(f))])
        t_colapso = None

    traza = {
        'nadir': nadir,
        't_nadir': t_nadir,
        't_colapso': t_colapso,
        'f_final': float(f[-1]),
        'rocof_inicial': float((f[1] - f[0]) / DT),
        'colapso': colapso,
        'aporte_primaria': float(dP_prim),
        'aporte_agc': float(dP_agc),
        'aporte_lfsm': float(dP_lfsm),
        'eventos': ev,
        'escalones': escalones,
        'deslastre_total': float(carga_deslastrada),
        'bombeo_deslastrado': float(bombeo_deslastrado),
        'escalones_bombeo': escalones_bombeo,
        'perturbacion_total': float(sum(e['dP_gen'] + e['dP_carga'] for e in ev)),
    }
    return t, f, traza
