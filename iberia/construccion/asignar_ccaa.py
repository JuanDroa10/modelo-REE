"""Asigna cada barra espanola a su comunidad autonoma.

    python -m iberia.construccion.asignar_ccaa RUTA/ne_10m_admin_1_states_provinces.shp

Escribe data/fuentes/bus_ccaa.csv (bus_id, ccaa), que es lo unico
que la cadena de construccion necesita: el contorno de 15 MB NO forma parte
del repositorio, solo hace falta para regenerar esta tabla.
Por la misma razon necesita geopandas, que no esta en requirements.txt: la
cadena de construccion lee la tabla ya hecha y no lo usa.

Para que existe (6-nov-2026). La demanda del dataset de Nokandi se reparte
por poblacion -cada km2 de WorldPop a la barra mas cercana- y el resultado
ponia el 37,5 % de la demanda espanola en Madrid, cuando REE da el 11,8 %.
build_full_network.py reescala ahora la demanda de cada comunidad a su
cuota de REE (demanda_ccaa_ree_2024.csv) y para eso tiene que saber en que
comunidad esta cada barra.

Fuente del contorno: Natural Earth, Admin 1 - States, Provinces, escala
1:10m (dominio publico), https://www.naturalearthdata.com/. Cada provincia
trae su comunidad en el campo `region`.

Una barra que cae fuera de todos los poligonos (en la costa, por la
resolucion del contorno) se asigna a la provincia mas cercana; el script
dice cuantas y a que distancia, para que no pase inadvertido.
"""
import os
import sys

import geopandas as gpd
import pandas as pd

from iberia import config

# Nombre de Natural Earth -> nombre de la tabla de REE.
NOMBRES = {
    'Andalucía': 'Andalucia', 'Aragón': 'Aragon', 'Asturias': 'Asturias',
    'Cantabria': 'Cantabria', 'Castilla y León': 'Castilla y Leon',
    'Castilla-La Mancha': 'Castilla-La Mancha', 'Cataluña': 'Cataluna',
    'Extremadura': 'Extremadura', 'Foral de Navarra': 'Navarra',
    'Galicia': 'Galicia', 'Islas Baleares': 'Baleares',
    'La Rioja': 'La Rioja', 'Madrid': 'Madrid', 'Murcia': 'Murcia',
    'País Vasco': 'Pais Vasco', 'Valenciana': 'C. Valenciana',
    'Canary Is.': 'Canarias', 'Ceuta': 'Ceuta', 'Melilla': 'Melilla',
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    prov = gpd.read_file(sys.argv[1])
    prov = prov[prov.adm0_a3 == 'ESP'][['region', 'geometry']].copy()
    prov['ccaa'] = prov.region.map(NOMBRES)
    falta = prov[prov.ccaa.isna()].region.unique()
    if len(falta):
        raise SystemExit('comunidades sin nombre en NOMBRES: %s' % falta)

    buses = pd.read_csv(config.dato('bus_data.csv'))
    buses = buses[buses.country == 'ES'].dropna(subset=['x', 'y'])
    pts = gpd.GeoDataFrame(buses[['bus_id']],
                           geometry=gpd.points_from_xy(buses.x, buses.y),
                           crs='EPSG:4326')
    dentro = gpd.sjoin(pts, prov[['ccaa', 'geometry']], how='left',
                       predicate='within').drop_duplicates('bus_id')
    fuera = dentro[dentro.ccaa.isna()]
    if len(fuera):
        # Distancias en un sistema metrico (UTM 30N) para que el
        # "mas cercano" sea en km y no en grados.
        p_m = pts.set_index('bus_id').loc[fuera.bus_id].to_crs(25830)
        prov_m = prov.to_crs(25830)
        cerca = gpd.sjoin_nearest(p_m.reset_index(), prov_m[['ccaa', 'geometry']],
                                  distance_col='dist_m')
        cerca = cerca.drop_duplicates('bus_id').set_index('bus_id')
        dentro = dentro.set_index('bus_id')
        dentro.loc[cerca.index, 'ccaa'] = cerca.ccaa
        dentro = dentro.reset_index()
        print('  %d barras fuera de los poligonos, asignadas a la provincia '
              'mas cercana (maximo %.1f km)' % (len(cerca),
                                                 cerca.dist_m.max() / 1e3))
    out = dentro[['bus_id', 'ccaa']].sort_values('bus_id')
    ruta = config.dato('bus_ccaa.csv')
    out.to_csv(ruta, index=False)
    print('  %d barras -> %s' % (len(out), os.path.relpath(ruta)))
    print(out.ccaa.value_counts().to_string())
    return 0


if __name__ == '__main__':
    sys.exit(main())
