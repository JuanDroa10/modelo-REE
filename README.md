# Modelo-Iberia — dinámica de frecuencia y generación detrás del contador del sistema eléctrico ibérico

Modelo de la **red de transporte peninsular española** de 220 y 400 kV, desarrollado sobre [PyPSA](https://pypsa.org/), que incorpora Portugal y Francia como sistemas eléctricos vecinos. Sobre esta representación se implementan cuatro capas principales de análisis:

- **Contingencias N-1:** evaluación mediante flujo de potencia AC e incorporación de los límites de capacidad de potencia reactiva de cada máquina.
- **Dinámica de frecuencia:** simulación de la respuesta del sistema ante perturbaciones, considerando el esquema de deslastre por mínima frecuencia de Red Eléctrica de España (P.O. 1.6), compuesto por seis escalones, la regulación primaria, la regulación secundaria (AGC) y el modo de respuesta a sobrefrecuencia (LFSM-O).
- **Análisis de cascada:** simulación de una secuencia de eventos que relaciona la pérdida de generación con la desconexión de generación detrás del contador (*Behind-the-Meter*, BTM).
- **Deslastre de carga considerando el BTM:** formulación mediante programación lineal entera mixta (MILP) para asignar las barras a los escalones del P.O. 1.6 y minimizar la desconexión de generación embebida que permanece en servicio.

El modelo incluye tres puntos de operación preparados para su simulación. Entre ellos se encuentra la **reconstrucción del sistema del 28 de abril de 2025 a las 12:33 h**, correspondiente al instante previo al apagón ibérico. La respuesta dinámica obtenida para este escenario se compara con el registro de frecuencia medido ese día.

> **Alcance de los resultados.** Los puntos de operación son reconstrucciones elaboradas a partir de fuentes públicas; no corresponden a un registro completo del estado de la red proporcionado por el operador. Por tanto, permiten estudiar el comportamiento del sistema bajo las hipótesis implementadas, pero no deben interpretarse como una reproducción exacta de las condiciones operativas. Para más detalles, consulta la sección [Alcance del modelo](#alcance-del-modelo).

## Requisitos

- **Python 3.11 o superior.** PyPSA 1.x requiere una versión compatible de Python; con las versiones 3.10 y anteriores la instalación no se completa. Comprueba los intérpretes instalados antes de crear el entorno:

  ```powershell
  py --list          # Windows: intérpretes instalados
  ```

  ```bash
  python3 --version  # macOS o Linux
  ```

  Si la versión disponible es la 3.10 o anterior, instala una versión más reciente y selecciónala al crear el entorno virtual.

- **Dependencias de Python.** Se instalan a partir de `requirements.txt`. Entre ellas se encuentran PyPSA, pandas, NumPy, SciPy, NetworkX, matplotlib, netCDF4, linopy y HiGHS (solucionador utilizado por el MILP de deslastre), además de folium para la generación del mapa interactivo.

## Primeros pasos

El repositorio incluye los datos de entrada y las redes ya construidas. Por ello, las simulaciones pueden ejecutarse desde el primer uso sin descargar información adicional ni disponer de conexión a internet. La conexión solo es necesaria para visualizar el fondo cartográfico del mapa interactivo.

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python menu.py
```

Si la activación del entorno mediante `Activate.ps1` falla debido a la política de ejecución (*Execution Policy*), puedes habilitar la ejecución de scripts para la ventana actual de PowerShell y volver a intentarlo:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### macOS o Linux (Bash)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python menu.py
```

### El menú

Al iniciar, el menú solicita seleccionar el **punto de operación** sobre el que se realizarán los análisis. Esta selección se mantiene durante la sesión hasta que se cambie explícitamente:

```text
SOBRE QUE PUNTO DE OPERACION QUIERES TRABAJAR
  1) 28-abr-2025 12:33 (apagon iberico)
  2) 15-ene 20-21 h (punta invernal nocturna)
  3) exportacion generica de 3.000 MW (despacho uniforme)
```

A continuación, el menú presenta las opciones disponibles en dos grupos:

- **Análisis asociados al punto de operación:** funciones de simulación, consulta, análisis y generación de mapas que utilizan el escenario seleccionado.
- **Funciones generales del modelo:** comparación de escenarios, generación de los mapas de la red y descripción de la construcción de cada escenario, que no dependen de un único punto de operación.

El menú está orientado a la simulación y exploración del sistema. Las comprobaciones internas del modelo y la reconstrucción de las redes no forman parte de él y se ejecutan desde la línea de comandos (véase [Comprobaciones](#comprobaciones)).

Antes de ejecutar una opción, el menú indica el escenario sobre el que trabaja y proporciona una descripción de la tarea. Algunas funciones no están disponibles para determinados puntos de operación. Por ejemplo, el análisis del umbral de penetración de BTM no se ofrece para la punta nocturna, ya que en ese escenario la generación solar es nula. El menú informa cuando se presenta esta condición. El punto de operación puede cambiarse en cualquier momento mediante la tecla `p`.

La [**GUIA_DE_USO.md**](GUIA_DE_USO.md) describe las opciones del menú, sus preguntas, los valores predeterminados y la interpretación de los resultados.

## Comandos

Los módulos de análisis también pueden ejecutarse directamente desde la línea de comandos, junto con algunas herramientas que el menú no incluye, como el cálculo de los indicadores del modelo y la ejecución por lotes. Los siguientes comandos deben ejecutarse desde el directorio raíz del repositorio:

| Comando | Descripción |
|---|---|
| `python -m iberia.estado_actual` | Presenta los principales indicadores del modelo, recalculados a partir de la configuración actual. |
| `python -m iberia.barrido_rapido --red apagon` | Ejecuta el barrido N-1 completo del escenario de apagón (3.277 contingencias). |
| `python -m iberia.barrido_rapido --red punta --plan` | Presenta el número de contingencias por clase y una estimación del coste computacional del barrido. |
| `python -m iberia.analisis_btm_cascada --red apagon` | Analiza el evento del 28 de abril de 2025, considerando los casos con y sin desconexión de BTM. |
| `python -m iberia.deslastre_btm_espana --red apagon --caida 80` | Compara el deslastre que considera el BTM con el reparto proporcional. |
| `python -m iberia.umbral_penetracion --red apagon --sensibilidad` | Evalúa el nivel de penetración de BTM a partir del cual se activa el deslastre. |
| `python -m iberia.validar_traza_28a` | Compara la respuesta dinámica simulada con el registro de frecuencia medido durante el evento del 28 de abril. |
| `python -m iberia.comparar_escenarios --n1 0` | Compara los escenarios de apagón y punta invernal. |
| `python -m iberia.barrido_lambda_normal` | Evalúa el efecto del peso λ del MILP en condiciones de operación normal. |
| `python -m iberia.calibrar_lambda_espana` | Ejecuta el procedimiento completo de calibración de λ. |
| `python -m iberia.mapas todos --red apagon` | Genera los mapas de la red, del BTM y de la cargabilidad. |
| `python -m iberia.visualize_network` | Genera una representación de la red sobre un fondo cartográfico y un mapa interactivo en HTML. |
| `python -m tools.correr_todo --rapido` | Ejecuta el conjunto de análisis del proyecto en modo por lotes, omitiendo los pasos de mayor coste computacional. |

Los módulos de simulación que admiten la selección de escenario utilizan el argumento `--red {apagon,punta,escenario}`:

```bash
python -m iberia.deslastre_btm_espana --red punta
python -m iberia.mapas carga --red punta
python -m iberia.barrido_rapido --red punta --procesos 8
```

Los resultados se almacenan en `resultados/`. Los nombres de los archivos incluyen el punto de operación correspondiente —por ejemplo, `contingencias_n1_apagon.csv` y `comparacion_deslastre_punta.csv`— para distinguir las ejecuciones y evitar que los resultados de un escenario sobrescriban los de otro.

El repositorio incluye en `data/referencia/` los resultados de los barridos N-1 de los dos escenarios principales. Esto permite consultar los rankings de contingencias y sus figuras sin ejecutar previamente los barridos. Cuando se realiza un nuevo barrido, las consultas posteriores utilizan los resultados generados por esa ejecución.

## Comprobaciones

El repositorio incluye las siguientes pruebas para comprobar distintos aspectos del modelo. No forman parte del menú y se ejecutan desde la línea de comandos:

```bash
python -m tests.verificar_parametros_linea        # impedancias frente a la impedancia característica
python -m tests.verificar_invariancia_frecuencia  # invariantes de la dinámica
python -m tests.verificar_respuesta_frecuencia    # retorno a 50 Hz: regulación primaria, AGC y LFSM-O
python -m tests.verificar_escalones_espana        # seis escalones del P.O. 1.6
python -m tests.verificar_milp_espana             # restricciones y garantías del MILP de deslastre
python -m tests.verificar_limites_reactivos       # curva de capacidad y transición PV-PQ
python -m tests.verificar_compensacion            # compensación shunt
python -m tests.verify_pt_fr_flows                # intercambios con Portugal y Francia
```

Para reconstruir las redes a partir de los archivos CSV de origen y comprobar que el proceso reproduce los modelos incluidos en el repositorio, ejecuta los siguientes comandos. Ten en cuenta que este procedimiento **reescribe el contenido de `data/redes/`**:

```bash
python -m tests.test_pipeline_smoke
python -m iberia.construccion.build_blackout_snapshot
python -m iberia.construccion.build_punta_snapshot
python -m iberia.construccion.dimensionar_trafos --aplicar
```

Los cuatro pasos deben ejecutarse en el orden indicado. Si alguno falla, no deben ejecutarse los siguientes.

## Estructura

```text
menu.py           punto de entrada interactivo
GUIA_DE_USO.md    manual del menú, con la descripción de cada opción
iberia/           módulos del modelo
  config.py         configuración, rutas y puntos de operación
  construccion/     proceso de construcción de las redes a partir de los CSV de origen
  ...               flujo de potencia, N-1, límites de reactivo, frecuencia,
                    BTM, deslastre, cascada y mapas
data/
  fuentes/          archivos CSV de la red, reparto de la demanda y contorno geográfico
  redes/            redes PyPSA construidas para cada punto de operación
  referencia/       barridos N-1 de referencia de los dos escenarios principales
tests/            pruebas y verificaciones del modelo
tools/            herramientas para ejecutar el proyecto por lotes
resultados/       archivos de salida: CSV, figuras y mapas (se crea automáticamente)
```

## Alcance del modelo

- **Puntos de operación.** El escenario del **apagón** se reconstruye a partir de la combinación de generación e intercambios publicados para las 12:33 h del 28 de abril de 2025; su respuesta dinámica se compara con el registro de frecuencia medido ese día. El escenario de **punta invernal** se deriva de las cuotas medias de generación por tecnología correspondientes a enero. El **escenario genérico** representa una exportación sintética de 3.000 MW.
- **Representación de Portugal y Francia.** Ambos países se modelan mediante sistemas agregados por tecnología conectados a sus respectivos puntos de interconexión; no se representan sus redes internas. Portugal forma parte de la isla síncrona y contribuye al cálculo de la inercia del sistema. Francia se representa como una condición de contorno. La carga de los nudos agregados de ambos países no se contabiliza como carga española en el análisis N-1.
- **Distribución de la demanda.** La demanda se asigna a las barras según el criterio de población del conjunto de datos original, y el total de cada comunidad autónoma se ajusta a la demanda publicada por REE para 2024. Sin este ajuste, el conjunto de datos asignaba a Madrid el 37,5 % de la demanda española, frente al 11,8 % registrado. La distribución interna de cada comunidad no representa la demanda industrial, que no sigue el criterio de población.
- **Análisis N-1 en el escenario de punta.** El caso base de este escenario presenta 5 ramas con una cargabilidad entre el 106 % y el 120 %, debidas al despacho uniforme sin orden de mérito. Los resultados de cada contingencia se expresan como incremento respecto a ese caso base. El caso base del escenario del apagón no presenta sobrecargas.
- **Escenario genérico.** Presenta 12 barras con tensiones entre 1,10 y 1,11 pu en condiciones de carga baja, ya que la compensación reactiva del modelo es fija y no representa la maniobra de reactores. Sus resultados de tensión no deben utilizarse como referencia.
- **Estimación de la inercia.** La inercia se calcula por tecnología a partir de la capacidad acoplada en cada punto de operación; no se dispone de una estimación individual para cada máquina. Las unidades que se desconectan durante una cascada conservan su contribución a la inercia y a la reserva, por lo que los tiempos de colapso obtenidos son ligeramente optimistas (en el escenario del apagón con solo los cuatro escalones generales, 6,7 s frente a 5,3 s si se descontara dicha contribución).
- **Resolución temporal.** Cada punto de operación representa un instante concreto y no una serie temporal.

## Fuentes de datos

- **Red, generación y demanda:** Nokandi, E. (2025). *Data of the Spanish Electric Power System* (v1.0.0) [Dataset]. Zenodo. [https://doi.org/10.5281/zenodo.14748878](https://doi.org/10.5281/zenodo.14748878). Licencia [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Los cinco archivos del conjunto incluidos en `data/fuentes/` (`bus_data.csv`, `line_data.csv`, `generation_data.csv`, `load_distribution_data.csv` y `load_time_series_data.csv`) corresponden a los datos originales sin modificar. Las transformaciones se realizan mediante los módulos de `iberia/construccion/`.
- **Distribución de la demanda por comunidad autónoma:** demanda de 2024 en barras de central publicada por Red Eléctrica de España a través de la API pública [REData](https://apidatos.ree.es) (véase `data/fuentes/demanda_ccaa_ree_2024.LEEME.txt`). La comunidad autónoma de cada barra (`data/fuentes/bus_ccaa.csv`) se asignó a partir del contorno de provincias de [Natural Earth](https://www.naturalearthdata.com/) (Admin 1, escala 1:10m) mediante `python -m iberia.construccion.asignar_ccaa RUTA/ne_10m_admin_1_states_provinces.shp`. Este contorno no se incluye en el repositorio y el módulo requiere `geopandas`, que no forma parte de `requirements.txt`; ambos solo son necesarios para regenerar la tabla, ya que el proceso de construcción utiliza la incluida en el repositorio.
- **Punto de operación del 28 de abril de 2025:** informe de NERC, *Iberian Peninsula Blackout – Contextual Comparison with North America* (26 de junio de 2025), junto con las cifras de generación e intercambio publicadas por REE y ENTSO-E para ese instante.
- **Comparación de la dinámica:** registro de frecuencia medido en Málaga por Fraunhofer ISE y reproducido en el informe de NERC.
- **Esquema de deslastre:** Procedimiento de Operación P.O. 1.6 de Red Eléctrica de España (BOE-A-1998-20053 y BOE-A-2009-8813).
- **Escenario de punta:** cuotas medias de generación por tecnología correspondientes a enero, publicadas por REE.
- **Contorno geográfico de los mapas:** [Natural Earth](https://www.naturalearthdata.com/), cuyos datos se distribuyen en dominio público.

Si utilizas este modelo en un trabajo académico o una publicación, incluye la referencia al conjunto de datos de Nokandi (2025) y cumple las condiciones de atribución de la licencia CC BY 4.0.

## Cómo colaborar

Las contribuciones más útiles son aquellas que permitan sustituir las reconstrucciones o los valores agregados por tecnología por información específica del sistema. En particular:

- **Datos de inercia y estatismo por unidad** del parque de generación español, para sustituir los valores por tecnología utilizados en `iberia/dinamica_frecuencia.py`.
- **Despacho real por unidad** para un instante determinado, que permita construir puntos de operación con el compromiso individual de las unidades de generación.
- **Capacidad de los transformadores y límites de emergencia por rama** basados en información técnica verificable.

Toda contribución de datos debe incluir la fuente correspondiente. Antes de enviar un *pull request*, deben ejecutarse y superarse las comprobaciones disponibles en `tests/`.

## Licencia

El código se distribuye bajo la licencia MIT. Consulta el archivo [LICENSE](LICENSE) para conocer sus condiciones. Los datos del conjunto de Nokandi incluidos en `data/fuentes/` conservan su licencia original, CC BY 4.0; los datos de REE y Natural Earth mantienen sus respectivas condiciones de uso (consulta la sección [Fuentes de datos](#fuentes-de-datos)).
