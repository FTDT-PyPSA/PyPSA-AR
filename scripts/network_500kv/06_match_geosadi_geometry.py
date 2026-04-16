"""
06_match_geosadi_geometry.py
Assigns WKT(well-known text) geometry to 500 kV PSS/E lines by matching against the
lineas_alta_tension layer from GeoSADI.

Depends : data/network_500kv/buses_final.csv          (script 05)
          data/network_500kv/lines_500kv_raw.csv       (script 02)
          data/network_500kv/manual_line_mappings.csv  (manual matching dictionary — versioned in repo)
              Created to resolve lines that could not be matched automatically,
              either due to naming inconsistencies between PSS/E and GeoSADI,
              or ambiguous parallel circuits.
          GEOSADI/GEOJSON/lineas_alta_tension.geojson  (external — download from GitHub Releases, place in external_data_dir/GEOSADI/GEOJSON/)
          aliases_500kv.py                             (same directory as this script)
Output  : data/network_500kv/lines_500kv_final.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/06_match_geosadi_geometry.py

Matching logic:

    STEP 0 — before any path:
        If element_type == 'series_compensator'
            -> geometry = '', match_status = 'series_compensator', continue

    STEP 1 — manual dictionary:
        If line_key is in manual_line_mappings.csv
            -> assign geometry by geosadi_line_id
            -> match_status = 'manual_geo'

    PATH A — both buses have name_geosadi:
        Name-based matching using aliases_500kv.py.
        ckt A/B/C is mapped to 1/2/3 to disambiguate parallel lines.
        1 candidate                  -> match_status = 'direct'
        Multiple (parallel lines)    -> disambiguate by circuit number
                                     -> match_status = 'parallel'
        No candidate                 -> match_status = 'no_match'

    PATH B — bus without name_geosadi and not in manual dictionary:
        -> geometry = '', match_status = 'pending_bus'
"""

import os
import sys
import json
import unicodedata
import csv
import re
from pathlib import Path
import yaml

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aliases_500kv import ALIASES

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

GEOJSON_FILE = EXTERNAL_DIR / "GEOSADI/GEOJSON/lineas_alta_tension.geojson"
BUSES_FINAL  = REPO_DIR / "data/network_500kv/buses_final.csv"
LINES_RAW    = REPO_DIR / "data/network_500kv/lines_500kv_raw.csv"
MANUAL_MAP   = REPO_DIR / "data/network_500kv/manual_line_mappings.csv"
OUTPUT_FILE  = REPO_DIR / "data/network_500kv/lines_500kv_final.csv"


# =============================================================================
# NORMALIZATION AND ALIASES
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
    Normalizes a GeoSADI line name and extracts tokens resolved via aliases.
    Returns a set of canonical substation names.
    """
    clean = re.sub(r'\s+500\s*\d*\s*$', '', nombre.strip())
    norm  = normalize(clean)
    tokens = norm.split()
    resolved = set()
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
                    resolved.add(normalize(val))
                used |= pos
            elif token_sp in ALIASES:
                val = ALIASES[token_sp]
                if val is not None:
                    resolved.add(normalize(val))
                used |= pos

    remaining_pos = set(range(len(tokens))) - used
    for i in remaining_pos:
        resolved.add(tokens[i])

    return resolved


def get_circuit_number(nombre):
    m = re.search(r'500\s+(\d+)\s*$', nombre.strip())
    return int(m.group(1)) if m else None


# =============================================================================
# GEOMETRY
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
    print("06_match_geosadi_geometry.py -- GeoSADI geometry to 500 kV lines")
    print("=" * 60)

    for f in [BUSES_FINAL, LINES_RAW, GEOJSON_FILE, MANUAL_MAP]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            return

    # --- Load buses ---
    bus_to_geosadi = {}
    with open(BUSES_FINAL, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            bid = int(row['bus_id'])
            bus_to_geosadi[bid] = normalize(row.get('name_geosadi', '') or '')

    # --- Load manual dictionary line_key -> geosadi_line_id ---
    manual_map = {}
    df_manual = pd.read_csv(MANUAL_MAP)
    for _, row in df_manual.iterrows():
        manual_map[row['line_key'].strip()] = int(row['geosadi_line_id'])
    print(f"\nManual dictionary loaded  : {len(manual_map)} entries")

    # --- Load PSS/E lines ---
    with open(LINES_RAW, encoding='utf-8') as f:
        lines = list(csv.DictReader(f))
    print(f"PSS/E lines loaded        : {len(lines)}")

    # --- Load GeoJSON ---
    with open(GEOJSON_FILE, encoding='utf-8') as f:
        gj = json.load(f)

    geo_lines_500 = [
        feat for feat in gj['features']
        if feat.get('geometry') and feat['properties'].get('Tension') == 500
    ]
    print(f"GeoSADI 500 kV lines      : {len(geo_lines_500)}")

    # Pre-process GeoSADI entries
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
    count = {
        'direct'           : 0,
        'parallel'         : 0,
        'manual_geo'       : 0,
        'series_compensator': 0,
        'pending_bus'      : 0,
        'no_match'         : 0,
    }
    output_rows = []

    for line in lines:
        bid_i  = int(line['bus_i'])
        bid_j  = int(line['bus_j'])
        ckt    = line['ckt'].strip()
        etype  = line.get('element_type', 'line')
        lkey   = line['line_key']

        # -------------------------------------------------------
        # STEP 0 — series compensators always first
        # -------------------------------------------------------
        if etype == 'series_compensator':
            row = dict(line)
            row['geo_nombre']   = ''
            row['match_status'] = 'series_compensator'
            row['geometry']     = ''
            output_rows.append(row)
            count['series_compensator'] += 1
            continue

        try:
            ckt_num = int(ckt)
        except ValueError:
            ckt_num = None

        # -------------------------------------------------------
        # STEP 1 — manual dictionary
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
                row['geo_nombre']   = f'ID {geosadi_lid} not found in GeoSADI'
                row['match_status'] = 'manual_geo'
                row['geometry']     = ''
                print(f"  [WARN] {lkey} — geosadi_line_id={geosadi_lid} not found in GeoJSON")
            output_rows.append(row)
            count['manual_geo'] += 1
            continue

        geo_i = bus_to_geosadi.get(bid_i, '')
        geo_j = bus_to_geosadi.get(bid_j, '')

        # -------------------------------------------------------
        # PATH A — both buses have name_geosadi
        # -------------------------------------------------------
        if geo_i and geo_j:
            candidates = [
                g for g in geo_by_name
                if geo_i in g['tokens'] and geo_j in g['tokens']
            ]

            if len(candidates) == 0:
                row = dict(line)
                row['geo_nombre']   = ''
                row['match_status'] = 'no_match'
                row['geometry']     = ''
                output_rows.append(row)
                count['no_match'] += 1

            elif len(candidates) == 1:
                g = candidates[0]
                row = dict(line)
                row['geo_nombre']   = g['nombre']
                row['match_status'] = 'direct'
                row['geometry']     = g['wkt']
                output_rows.append(row)
                count['direct'] += 1

            else:
                match = None
                if ckt_num is not None:
                    for c in candidates:
                        if c['ckt_num'] == ckt_num:
                            match = c
                            break

                if match:
                    row = dict(line)
                    row['geo_nombre']   = match['nombre']
                    row['match_status'] = 'parallel'
                    row['geometry']     = match['wkt']
                    output_rows.append(row)
                    count['parallel'] += 1
                else:
                    row = dict(line)
                    row['geo_nombre']   = f"AMBIGUOUS: {candidates[0]['nombre']}"
                    row['match_status'] = 'no_match'
                    row['geometry']     = ''
                    output_rows.append(row)
                    count['no_match'] += 1

        # -------------------------------------------------------
        # PATH B — bus without name_geosadi
        # -------------------------------------------------------
        else:
            row = dict(line)
            row['geo_nombre']   = ''
            row['match_status'] = 'pending_bus'
            row['geometry']     = ''
            output_rows.append(row)
            count['pending_bus'] += 1

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"MATCHING SUMMARY")
    print(f"{'='*60}")
    for status, n in count.items():
        print(f"  {status:<22}: {n}")
    print(f"  {'TOTAL':<22}: {sum(count.values())}")

    # --- Export ---
    df_out = pd.DataFrame(output_rows)
    df_out.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df_out)} rows)")
    print("Next: 07_validate_topology.py")


if __name__ == "__main__":
    main()
