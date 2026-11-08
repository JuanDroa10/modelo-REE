"""Corre el proyecto entero, en orden de dependencias, y reporta que pasa
y que falla.

Es el "menu completo": si esto termina en verde, el modelo esta en un
estado consistente y reproducible desde los CSV de origen.

ORDEN, y por que importa:
  1. La cadena de construccion (via el smoke test, que la corre entera y
     ademas valida los conteos). DESTRUCTIVO: reescribe los .nc.
  2. Los verificadores de la red, que solo tienen sentido sobre una red
     recien construida.
  3. El punto de operacion del apagon, que se deriva de la red anterior.
  4. Dinamica (D) y deslastre (E), que leen ese punto de operacion.
  5. El N-1, que es lo mas caro y no condiciona a nada mas.

Uso:
    python correr_todo.py            # todo
    python correr_todo.py --rapido   # salta lo que tarda mas de ~5 min
"""
import argparse
import subprocess
import sys
import time

from iberia.config import RAIZ

# (script, args, minutos_estimados, saltar_con_rapido)
#
# El ultimo campo no es solo "tarda mucho": tambien marca los pasos que
# DEPENDEN de uno caro. `visualize_n1.py` tarda 2 min, pero dibuja el
# barrido N-1; si --rapido se salta el barrido y deja la visualizacion,
# esa corrida dibuja un barrido que ella NO produjo --- la misma trampa
# de la que viene todo esto, solo que movida un paso mas abajo.
PASOS = [
    # --- 1. cadena de construccion -------------------------------------
    ("tests.test_pipeline_smoke", [], 3, False),

    # --- 2. verificadores de la red ------------------------------------
    ("tests.verificar_parametros_linea", [], 1, False),
    ("tests.verify_pt_fr_flows", [], 1, False),

    # --- 3. los dos puntos de operacion, y el dimensionado que depende
    #        de los dos -------------------------------------------------
    #
    # AQUI FALTABAN DOS PASOS, y su ausencia hacia que esta cadena
    # DEGRADARA el modelo en vez de reproducirlo (corregido el
    # 2-nov-2026). Medido: una corrida completa dejaba los 179
    # transformadores en la semilla provisional de `fix_network_v2.py`
    # ---s_nom = 1.000 MVA para todos, r = 0,010--- deshaciendo el
    # dimensionado por flujo real. El total pasaba de 130.500 MVA
    # repartidos en 12 valores distintos (150-6.000) a 179.000 MVA en un
    # unico valor, y la resistencia quedaba 4 veces por encima de la
    # real.
    #
    # Y el gate NO lo veia: `test_pipeline_smoke.py` comprueba CONTEOS
    # (1.225 buses, 179 trafos, 978 generadores) y el numero de
    # transformadores no cambia; solo cambian su s_nom y su r. Asi que la
    # corrida terminaba en verde habiendo revertido la fase 4.
    #
    # El orden importa y no es arbitrario: los dos snapshots derivan de
    # iberia_scenario.nc, y `dimensionar_trafos` necesita el flujo de LOS
    # DOS (la punta manda en 139 de los 179) antes de poder escribir.
    ("iberia.construccion.build_blackout_snapshot", [], 1, False),
    ("iberia.construccion.build_punta_snapshot", [], 1, False),
    ("iberia.construccion.dimensionar_trafos", ["--aplicar"], 2, False),

    # --- 4. dinamica de frecuencia (D) y deslastre (E) -----------------
    ("iberia.btm_regional", [], 1, False),
    ("tests.verificar_invariancia_frecuencia", [], 1, False),
    ("tests.verificar_respuesta_frecuencia", [], 1, False),
    ("iberia.analisis_btm_cascada", [], 2, False),
    ("tests.verificar_escalones_espana", [], 1, False),
    ("tests.verificar_milp_espana", [], 1, False),
    ("iberia.deslastre_btm_espana", [], 3, False),
    ("iberia.umbral_penetracion", [], 1, False),
    ("iberia.calibrar_lambda_espana", [], 1, True),

    # --- 5. flujo de potencia y N-1 (lo caro) --------------------------
    ("tests.verificar_limites_reactivos", [], 1, False),
    ("tests.verificar_compensacion", [], 1, False),
    # EL N-1 VIGENTE, no el retirado (corregido el 2-nov-2026).
    #
    # Aqui corria `analisis_n1.py --sin-limites`, que el propio README
    # declara RETIRADO por no ser fisicamente valido: sin limites de
    # reactivo el colapso de tension es imposible de observar por
    # construccion, asi que cualquier estudio de cascada sale benigno.
    # Es decir, el "menu completo" terminaba en verde habiendo producido
    # un resultado que el proyecto no se permite citar.
    #
    # Y el paso siguiente lo empeoraba: `visualize_n1.py` no dibujaba ni
    # siquiera ese barrido, sino el que `fuente_n1` encontrara primero,
    # que en esta copia era `contingencias_n1.csv` del 27 de septiembre.
    # Las dos mitades estan corregidas; ahora los dos pasos hablan del
    # MISMO escenario y de forma explicita.
    ("iberia.barrido_rapido", ["--red", "apagon"], 34, True),
    ("iberia.visualize_n1", ["--red", "apagon"], 2, True),   # depende del anterior
    ("iberia.visualize_network", [], 3, False),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rapido', action='store_true',
                    help="salta los pasos caros y los que dependen de ellos")
    args = ap.parse_args()

    pasos = [p for p in PASOS if not (args.rapido and p[3])]
    total_est = sum(p[2] for p in pasos)
    print(f"{'='*72}\n MENU COMPLETO: {len(pasos)} pasos, "
          f"~{total_est} min estimados\n{'='*72}\n", flush=True)
    if args.rapido:
        saltados = [p[0] for p in PASOS if p[3]]
        print(f"  --rapido: se saltan {len(saltados)} pasos "
              f"({', '.join(saltados)}).\n  Esta corrida NO produce barrido "
              f"N-1 ni lo visualiza.\n", flush=True)
    # El primer paso reescribe los .nc de la red. Decirlo antes, no despues.
    if any(p[0] == 'tests.test_pipeline_smoke' for p in pasos):
        print("  AVISO: el primer paso RECONSTRUYE la red desde los CSV y "
              "reescribe\n         data/redes/*.nc.\n", flush=True)

    resultados, t0 = [], time.time()
    for i, (script, extra, _, _) in enumerate(pasos, 1):
        etiqueta = script + (' ' + ' '.join(extra) if extra else '')
        print(f"[{i:2d}/{len(pasos)}] {etiqueta} ...", end=' ', flush=True)
        t1 = time.time()
        r = subprocess.run([sys.executable, '-m', script] + extra,
                           capture_output=True, text=True, cwd=str(RAIZ))
        dur = time.time() - t1
        ok = r.returncode == 0
        resultados.append((etiqueta, ok, dur, r.stdout, r.stderr))
        print(f"{'OK' if ok else 'FALLA'}  ({dur:.0f} s)", flush=True)
        if not ok:
            # Se muestra el fallo en el momento, pero NO se aborta: un
            # paso roto no deberia ocultar el estado de los demas.
            print("        --- stderr (ultimas lineas) ---")
            for linea in r.stderr.strip().splitlines()[-6:]:
                print(f"        {linea}")

    print(f"\n{'='*72}\n RESUMEN ({(time.time()-t0)/60:.0f} min)\n{'='*72}")
    fallos = [e for e, ok, *_ in resultados if not ok]
    for etiqueta, ok, dur, _, _ in resultados:
        print(f"  {'OK   ' if ok else 'FALLA'} {etiqueta:44s} {dur:6.0f} s")
    print()
    if fallos:
        print(f"{len(fallos)} de {len(resultados)} pasos FALLARON:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print(f"Los {len(resultados)} pasos pasaron. El modelo es reproducible "
          f"desde los CSV de origen.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
