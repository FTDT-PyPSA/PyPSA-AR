"""
06_match_geosadi_geometry.py
Asigna geometria (WKT) a las lineas 500 kV del PSS/E matcheando contra
el layer lineas_alta_tension del GeoSADI.

Depende de:
    buses_final.csv        (output script 05)
    lines_500kv_raw.csv          (output script 02)
    manual_line_mappings.csv     (diccionario line_key -> geosadi_line_id)
    lineas_alta_tension.geojson  (GeoSADI)
    aliases_500kv.py             (mismo directorio que este script)

Output:
    lines_500kv_final.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/06_match_geosadi_geometry.py

Logica de matching:

    PASO 0 — antes que cualquier camino:
        Si element_type == 'series_compensator'
            -> geometry = '', match_status = 'compensador', continuar

    PASO 1 — diccionario manual:
        Si line_key esta en manual_line_mappings.csv
            -> asignar geometria por geosadi_line_id
            -> match_status = 'manual_geo'

    CAMINO A — ambos buses tienen name_geosadi:
        Matching por nombre usando aliases_500kv.py.
        ckt A/B/C se mapea a 1/2/3 para desambiguar lineas paralelas.
        1 candidato                  -> match_status = 'directo'
        Multiples (lineas paralelas) -> desambiguar por numero de ckt
                                     -> match_status = 'paralela'
        Sin candidato                -> match_status = 'sin_match'

    CAMINO B — bus sin name_geosadi sin entrada en diccionario manual:
        -> geometry = '', match_status = 'pendiente_bus'
"""

import os
import sys
import json
import unicodedata
import csv
import re

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aliases_500kv import ALIASES

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
GEOJSON_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/GEOSADI/GEOJSON/lineas_alta_tension.geojson"

BUSES_FINAL   = os.path.join(DATA_DIR, "buses_final.csv")
LINES_RAW     = os.path.join(DATA_DIR, "lines_500kv_raw.csv")
MANUAL_MAP    = os.path.join(DATA_DIR, "manual_line_mappings.csv")
OUTPUT_FILE   = os.path.join(DATA_DIR, "lines_500kv_final.csv")



# =============================================================================
# NORMALIZACION Y ALIASES
# =============================================================================

def normalize(text):
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFD", str(text))
    s = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    s = s.upper()
    for ch in [".", "(", ")", "-", "_", "°"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())


def normalize_geosadi_name(nombre):
    """
    Normaliza el Nombre de una linea GeoSADI y extrae tokens resueltos via aliases.
    Devuelve set de nombres canonicos de estaciones.
    """
    clean = re.sub(r'\s+500\s*\d*\s*$', '', nombre.strip())
    norm  = normalize(clean)
    tokens = norm.split()
    resueltos = set()
    used = set()

    for size in range(4, 0, -1):
        for i in range(len(tokens) - size + 1):
            token    = "".join(tokens[i:i+size])
            token_sp = " ".join(tokens[i:i+size])
            pos = set(range(i, i+size))
            if pos & used:
                continue
            if token in ALIASES:
                val = ALIASES[token]
                if val is not None:
                    resueltos.add(normalize(val))
                used |= pos
            elif token_sp in ALIASES:
                val = ALIASES[token_sp]
                if val is not None:
                    resueltos.add(normalize(val))
                used |= pos

    remaining_pos = set(range(len(tokens))) - used
    for i in remaining_pos:
        resueltos.add(tokens[i])

    return resueltos


def get_circuit_number(nombre):
    m = re.search(r'500\s+(\d+)\s*$', nombre.strip())
    return int(m.group(1)) if m else None


# =============================================================================
# GEOMETRIA
# =============================================================================

def geom_to_coords(geom):
    if geom is None:
        return []
    if geom['type'] == 'LineString':
        return geom['coordinates']
    elif geom['type'] == 'MultiLineString':
        coords = []
        for part in geom['coordinates']:
            coords.extend(part)
        return coords
    return []


def coords_to_wkt(coords):
    if not coords:
        return ''
    points = ', '.join(f"{c[0]} {c[1]}" for c in coords)
    return f"LINESTRING ({points})"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("04_match_geosadi_geometry.py -- geometria GeoSADI a lineas 500 kV")
    print("=" * 60)

    for f in [BUSES_FINAL, LINES_RAW, GEOJSON_FILE, MANUAL_MAP]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            return

    # --- Cargar buses ---
    bus_to_geosadi = {}
    with open(BUSES_FINAL, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            bid = int(row['bus_id'])
            bus_to_geosadi[bid] = normalize(row.get('name_geosadi', '') or '')

    # --- Cargar diccionario manual line_key -> geosadi_line_id ---
    manual_map = {}
    df_manual = pd.read_csv(MANUAL_MAP)
    for _, row in df_manual.iterrows():
        manual_map[row['line_key'].strip()] = int(row['geosadi_line_id'])
    print(f"\nDiccionario manual cargado: {len(manual_map)} entradas")

    # --- Cargar lineas PSS/E ---
    with open(LINES_RAW, encoding='utf-8') as f:
        lines = list(csv.DictReader(f))
    print(f"Lineas PSS/E cargadas     : {len(lines)}")

    # --- Cargar GeoJSON ---
    with open(GEOJSON_FILE, encoding='utf-8') as f:
        gj = json.load(f)

    geo_lines_500 = [
        feat for feat in gj['features']
        if feat.get('geometry') and feat['properties'].get('Tension') == 500
    ]
    print(f"Lineas GeoSADI 500 kV     : {len(geo_lines_500)}")

    # Pre-procesar GeoSADI
    geo_by_id   = {}
    geo_by_name = []

    for feat in geo_lines_500:
        p      = feat['properties']
        geo_id = p['id']
        nombre = p['Nombre']
        tokens = normalize_geosadi_name(nombre)
        coords = geom_to_coords(feat['geometry'])
        entry  = {
            'id'      : geo_id,
            'nombre'  : nombre,
            'tokens'  : tokens,
            'ckt_num' : get_circuit_number(nombre),
            'wkt'     : coords_to_wkt(coords),
        }
        geo_by_id[geo_id] = entry
        geo_by_name.append(entry)

    # --- Matching ---
    conteo = {
        'directo'       : 0,
        'paralela'      : 0,
        'manual_geo'    : 0,
        'compensador'   : 0,
        'pendiente_bus' : 0,
        'sin_match'     : 0,
    }
    output_rows = []

    for line in lines:
        bid_i  = int(line['bus_i'])
        bid_j  = int(line['bus_j'])
        ckt    = line['ckt'].strip()
        etype  = line.get('element_type', 'line')
        lkey   = line['line_key']

        # -------------------------------------------------------
        # PASO 0 — compensadores siempre primero
        # -------------------------------------------------------
        if etype == 'series_compensator':
            row = dict(line)
            row['geo_nombre']   = ''
            row['match_status'] = 'compensador'
            row['geometry']     = ''
            output_rows.append(row)
            conteo['compensador'] += 1
            continue

        try:
            ckt_num = int(ckt)
        except ValueError:
            ckt_num = None

        # -------------------------------------------------------
        # PASO 1 — diccionario manual
        # -------------------------------------------------------
        if lkey in manual_map:
            geosadi_lid = manual_map[lkey]
            geo_entry   = geo_by_id.get(geosadi_lid)
            row = dict(line)
            if geo_entry:
                row['geo_nombre']   = geo_entry['nombre']
                row['match_status'] = 'manual_geo'
                row['geometry']     = geo_entry['wkt']
            else:
                row['geo_nombre']   = f'ID {geosadi_lid} no encontrado en GeoSADI'
                row['match_status'] = 'manual_geo'
                row['geometry']     = ''
                print(f"  [WARN] {lkey} — geosadi_line_id={geosadi_lid} no existe en GeoJSON")
            output_rows.append(row)
            conteo['manual_geo'] += 1
            continue

        geo_i = bus_to_geosadi.get(bid_i, '')
        geo_j = bus_to_geosadi.get(bid_j, '')

        # -------------------------------------------------------
        # CAMINO A — ambos buses tienen name_geosadi
        # -------------------------------------------------------
        if geo_i and geo_j:
            candidatos = [
                g for g in geo_by_name
                if geo_i in g['tokens'] and geo_j in g['tokens']
            ]

            if len(candidatos) == 0:
                row = dict(line)
                row['geo_nombre']   = ''
                row['match_status'] = 'sin_match'
                row['geometry']     = ''
                output_rows.append(row)
                conteo['sin_match'] += 1

            elif len(candidatos) == 1:
                g = candidatos[0]
                row = dict(line)
                row['geo_nombre']   = g['nombre']
                row['match_status'] = 'directo'
                row['geometry']     = g['wkt']
                output_rows.append(row)
                conteo['directo'] += 1

            else:
                match = None
                if ckt_num is not None:
                    for c in candidatos:
                        if c['ckt_num'] == ckt_num:
                            match = c
                            break

                if match:
                    row = dict(line)
                    row['geo_nombre']   = match['nombre']
                    row['match_status'] = 'paralela'
                    row['geometry']     = match['wkt']
                    output_rows.append(row)
                    conteo['paralela'] += 1
                else:
                    row = dict(line)
                    row['geo_nombre']   = f"AMBIGUO: {candidatos[0]['nombre']}"
                    row['match_status'] = 'sin_match'
                    row['geometry']     = ''
                    output_rows.append(row)
                    conteo['sin_match'] += 1
                    print(f"  [AMBIGUO] {lkey}  ckt={ckt}  candidatos: {[c['nombre'] for c in candidatos]}")

        # -------------------------------------------------------
        # CAMINO B — bus sin name_geosadi sin entrada en diccionario manual
        # -------------------------------------------------------
        else:
            row = dict(line)
            row['geo_nombre']   = ''
            row['match_status'] = 'pendiente_bus'
            row['geometry']     = ''
            output_rows.append(row)
            conteo['pendiente_bus'] += 1

    # --- Exportar ---
    if not output_rows:
        print("[ERROR] Sin filas para exportar")
        return

    fieldnames = list(output_rows[0].keys())
    for col in ['geo_nombre', 'match_status', 'geometry']:
        if col in fieldnames:
            fieldnames.remove(col)
    fieldnames += ['geo_nombre', 'match_status', 'geometry']

    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    # --- Reporte ---
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  directo        : {conteo['directo']}")
    print(f"  paralela       : {conteo['paralela']}")
    print(f"  manual_geo     : {conteo['manual_geo']}")
    print(f"  compensador    : {conteo['compensador']}")
    print(f"  pendiente_bus  : {conteo['pendiente_bus']}")
    print(f"  sin_match      : {conteo['sin_match']}")
    print(f"  TOTAL          : {len(output_rows)}")

    sin_match = [r for r in output_rows if r['match_status'] == 'sin_match']
    if sin_match:
        print(f"\nLineas sin geometria ({len(sin_match)}) — revisar aliases_500kv.py:")
        for r in sin_match:
            gi = bus_to_geosadi.get(int(r['bus_i']), '?')
            gj = bus_to_geosadi.get(int(r['bus_j']), '?')
            print(f"  {r['line_key']:<42}  [{gi}] — [{gj}]")

    pendiente = [r for r in output_rows if r['match_status'] == 'pendiente_bus']
    if pendiente:
        print(f"\nLineas pendiente_bus ({len(pendiente)}) — buses sin name_geosadi ni mapeo manual:")
        for r in pendiente:
            print(f"  {r['line_key']:<42}  bus_i={r['bus_i']}  bus_j={r['bus_j']}")

    print(f"\n✔ {OUTPUT_FILE}  ({len(output_rows)} filas)")
    print("Proximo: 07_validate_topology.py")


if __name__ == "__main__":
    main()
