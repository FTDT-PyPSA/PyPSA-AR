"""
Script 01 — build_500kv_buses.py
Proyecto: PyPSA-AR
Descripcion: Construye el catalogo de buses 500 kV a partir de estaciones_transformadoras.geojson (GeoSADI)
             Excluye estaciones internacionales definidas explicitamente en EXCLUIR_INTERNACIONALES.

Input:  estaciones_transformadoras.geojson
Output: buses_500kv.csv

"""

import json
import csv
import unicodedata
import os

# ── Rutas ──────────────────────────────────────────────────────────────────────
INPUT_GEOJSON = "/mnt/c/Work/pypsa-ar-sandbox/Official data/GEOSADI/GEOJSON/estaciones_transformadoras.geojson"
OUTPUT_CSV = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_500kv.csv"

# ── CONEXIONES INTERNACIONALES ─────────────────────────────────────────────────
# Estaciones que pertenecen a redes de paises vecinos y se excluyen del modelo.
# Omitir este bloque completo (constante + logica en el loop) si se desean incluir.
EXCLUIR_INTERNACIONALES = {
    'SAN_JAVIER',          # Uruguay — lado uruguayo del Rio Uruguay
    'SALTO_GRANDE_URG',    # Uruguay — lado uruguayo de la presa Salto Grande
    'GARABI',              # Brasil  — lado brasilero del Rio Uruguay
}
# ──────────────────────────────────────────────────────────────────────────────


def normalizar_nombre(nombre):
    """
    Convierte un nombre de estacion a bus_id limpio.
    Ejemplo: 'RINCÓN STA. MARÍA' -> 'RINCON_STA_MARIA'
    """
    nombre = nombre.strip()
    nombre = unicodedata.normalize('NFD', nombre)
    nombre = ''.join(c for c in nombre if unicodedata.category(c) != 'Mn')
    nombre = nombre.upper()
    nombre = nombre.replace(' ', '_').replace('-', '_')
    nombre = ''.join(c for c in nombre if c.isalnum() or c == '_')
    while '__' in nombre:
        nombre = nombre.replace('__', '_')
    return nombre.strip('_')


def main():
    # ── Cargar GeoJSON ─────────────────────────────────────────────────────────
    print(f"Cargando: {INPUT_GEOJSON}")
    with open(INPUT_GEOJSON, encoding='utf-8') as f:
        data = json.load(f)

    features = data['features']
    print(f"  Total features en archivo: {len(features)}")

    # ── Filtrar 500 kV ─────────────────────────────────────────────────────────
    estaciones_500 = [
        f for f in features
        if str(f['properties'].get('Tension', '')).strip() == '500'
    ]
    print(f"  Estaciones con Tension == 500: {len(estaciones_500)}")

    # ── Construir registros con filtro geografico ──────────────────────────────
    buses        = []
    excluidas    = []
    

    for feat in estaciones_500:
        props  = feat['properties']
        geom   = feat['geometry']
        nombre = props['Nombre'].strip()

        if geom['type'] != 'Point':
            print(f"  ADVERTENCIA: geometria inesperada '{geom['type']}' para '{nombre}' — omitida")
            continue

        lon, lat = geom['coordinates'][0], geom['coordinates'][1]
        bus_id   = normalizar_nombre(nombre)
        # ── CONEXIONES INTERNACIONALES ────────────────────────────────────────
        # Omitir este bloque completo si se desean incluir nodos internacionales.
        if bus_id in EXCLUIR_INTERNACIONALES:
            excluidas.append((bus_id, nombre, lon, lat))
            continue
        # ── fin bloque conexiones internacionales ─────────────────────────────

        buses.append({
            'bus_id': bus_id,
            'nombre': nombre,
            'lon'   : round(lon, 7),
            'lat'   : round(lat, 7),
            'v_nom' : 500,
        })

    # ── Reporte de exclusiones ─────────────────────────────────────────────────
    print()
    if excluidas:
        print(f"  Excluidas por estar fuera de Argentina ({len(excluidas)}):")
        for bus_id, nombre, lon, lat in excluidas:
            print(f"    - {nombre:<30} ({lon:.4f}, {lat:.4f})")

    print()
    print(f"  Buses a exportar: {len(buses)}")

    # ── Exportar CSV ───────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

    campos = ['bus_id', 'nombre', 'lon', 'lat', 'v_nom']
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(buses)

    print(f"CSV escrito en: {OUTPUT_CSV}")

    # ── Tabla resumen ──────────────────────────────────────────────────────────
    print()
    print(f"{'bus_id':<30} {'nombre':<35} {'lon':>12} {'lat':>10}")
    print("-" * 90)
    for b in buses:
        print(f"{b['bus_id']:<30} {b['nombre']:<35} {b['lon']:>12} {b['lat']:>10}")

    print()
    print(f"Listo. {len(buses)} buses 500 kV exportados.")


if __name__ == '__main__':
    main()