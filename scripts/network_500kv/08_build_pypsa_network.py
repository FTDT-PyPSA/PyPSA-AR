"""
08_build_pypsa_network.py
Construye el objeto PyPSA Network con la red 500 kV del SADI y lo exporta a .nc.

Inputs:
    data/network_500kv/buses_final.csv        (script 05 — todos los buses)
    data/network_500kv/lines_500kv_final.csv  (script 06 — lineas con geometria)
    data/network_500kv/trafos_500kv_raw.csv   (script 03 — transformadores)

Output:
    networks/network_500kv.nc

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/08_build_pypsa_network.py

Decisiones de modelado:
    BUSES:
        - Todos los buses del buses_final.csv (500kV + secundarios)
        - v_nom en kV, coordenadas x=lon, y=lat
        - Buses sin coordenadas se agregan igual (PyPSA no requiere lat/lon)

    LINEAS:
        - Impedancias del PSS/E en pu (Sbase=100 MVA confirmado en encabezado del .raw)
        - Conversion a unidades fisicas usando Zbase dinamico por linea:
            Z_base = baskv_kv(bus_i)² / S_base
          r [Ohm] = r_pu * Z_base
          x [Ohm] = x_pu * Z_base
          b [S]   = b_pu / Z_base
        - Se usa baskv_kv del bus_i (extremo i) como Vbase de la linea.
       
        - s_nom desde ratea_mva del PSS/E (MVA)
        - Lineas sin rating (ratea_mva=NaN): s_nom = 0 (sin limite)
        - Compensadores serie (x < 0) agregados como Line con x negativo
        - Se omiten lineas con match_status='pendiente_bus' (bus extremo sin datos)

    TRANSFORMADORES:
        - x_pu y r_pu del PSS/E asumidos en base sbase_mva del trafo (CZ=2 tipico)
        - s_nom = sbase_mva del PSS/E
        - Se omiten trafos con buses ausentes en buses_final.csv
        - Keys duplicados (3W descompuestos) se resuelven agregando sufijo _A, _B

    SNAPSHOT:
        - Un solo snapshot (2024-01-01) para poder exportar el .nc
        - Sin perfiles de carga/generacion en esta etapa
"""

import os
import sys
import pandas as pd
import numpy as np
import pypsa

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_DIR    = "/mnt/c/Work/pypsa-ar-base/networks"

BUSES_FILE    = os.path.join(DATA_DIR, "buses_final.csv")
LINES_FILE    = os.path.join(DATA_DIR, "lines_500kv_final.csv")
TRAFOS_FILE   = os.path.join(DATA_DIR, "trafos_500kv_raw.csv")
OUTPUT_FILE   = os.path.join(OUTPUT_DIR, "network_500kv.nc")

# Base del sistema PSS/E — confirmado en encabezado del .raw (linea 2, campo SBASE)
S_BASE_MVA = 100.0


# =============================================================================
# HELPERS
# =============================================================================

def safe_float(val, default=0.0):
    """Convierte a float, retorna default si es NaN o no parseable."""
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def make_unique_keys(keys):
    """
    Resuelve keys duplicados agregando sufijo _A, _B, _C...
    Retorna lista de keys unicos del mismo largo.
    """
    from collections import Counter
    count   = Counter()
    seen    = Counter()
    result  = []
    for k in keys:
        count[k] += 1
    for k in keys:
        if count[k] == 1:
            result.append(k)
        else:
            suffix = chr(ord('A') + seen[k])
            result.append(f"{k}_{suffix}")
            seen[k] += 1
    return result


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("08_build_pypsa_network.py -- construir PyPSA Network 500 kV")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    buses  = pd.read_csv(BUSES_FILE)
    lines  = pd.read_csv(LINES_FILE)
    trafos = pd.read_csv(TRAFOS_FILE)

    # Mapa bus_id -> bus_name (para resolver lineas y trafos)
    id_to_name  = dict(zip(buses['bus_id'].astype(int), buses['bus_name']))
    bus_vnom    = dict(zip(buses['bus_id'].astype(int), buses['baskv_kv'].astype(float)))
    all_bus_ids = set(buses['bus_id'].astype(int))

    # ==========================================================
    # CREAR RED
    # ==========================================================
    n = pypsa.Network()
    n.name = "SADI 500kV"
    n.set_snapshots(pd.DatetimeIndex(["2024-01-01"]))

    print(f"\n✔ Network creado")

    # ==========================================================
    # AGREGAR BUSES
    # ==========================================================
    print(f"\n[1] Agregando buses...")
    n_added_buses = 0
    n_sin_coord   = 0

    for _, row in buses.iterrows():
        lat = row['lat'] if pd.notna(row['lat']) else np.nan
        lon = row['lon'] if pd.notna(row['lon']) else np.nan
        if pd.isna(lat) or pd.isna(lon):
            n_sin_coord += 1

        n.add(
            "Bus",
            row['bus_name'],
            v_nom    = float(row['baskv_kv']),
            x        = lon,
            y        = lat,
            carrier  = "AC",
        )
        n_added_buses += 1

    print(f"    Buses agregados   : {n_added_buses}")
    if n_sin_coord:
        print(f"    ⚠ Sin coordenadas : {n_sin_coord} (agregados igual)")

    # ==========================================================
    # AGREGAR LINEAS
    # ==========================================================
    print(f"\n[2] Agregando lineas y compensadores...")
    n_lines       = 0
    n_comps       = 0
    n_skip_bus    = 0
    n_skip_svc    = 0

    for _, row in lines.iterrows():
        bus_i_id = int(row['bus_i'])
        bus_j_id = int(row['bus_j'])

        # Omitir si alguno de los buses no existe
        if bus_i_id not in all_bus_ids or bus_j_id not in all_bus_ids:
            n_skip_bus += 1
            continue

        # Omitir lineas fuera de servicio (match_status=pendiente_bus ya filtra T PEPE)
        if row['match_status'] == 'pendiente_bus':
            n_skip_bus += 1
            continue

        bus_i_name = id_to_name[bus_i_id]
        bus_j_name = id_to_name[bus_j_id]

        # Zbase dinamico usando baskv_kv del bus_i
        vbase  = bus_vnom[bus_i_id]
        z_base = (vbase ** 2) / S_BASE_MVA

        r_ohm  = safe_float(row['r_pu']) * z_base
        x_ohm  = safe_float(row['x_pu']) * z_base
        b_s    = safe_float(row['b_pu']) / z_base
        s_nom  = safe_float(row['ratea_mva'], default=0.0)

        n.add(
            "Line",
            row['line_key'],
            bus0   = bus_i_name,
            bus1   = bus_j_name,
            r      = r_ohm,
            x      = x_ohm,
            b      = b_s,
            s_nom  = s_nom,
        )

        if row['element_type'] == 'series_compensator':
            n_comps += 1
        else:
            n_lines += 1

    print(f"    Lineas agregadas       : {n_lines}")
    print(f"    Compensadores serie    : {n_comps}")
    if n_skip_bus:
        print(f"    ⚠ Omitidas (bus ausente o pendiente_bus): {n_skip_bus}")

    # ==========================================================
    # AGREGAR TRANSFORMADORES
    # ==========================================================
    print(f"\n[3] Agregando transformadores...")
    n_trafos     = 0
    n_skip_trafo = 0

    # Resolver keys duplicados (trafos 3W descompuestos)
    trafo_keys_raw  = list(trafos['trafo_key'])
    trafo_keys_uniq = make_unique_keys(trafo_keys_raw)
    n_renamed = sum(1 for a, b in zip(trafo_keys_raw, trafo_keys_uniq) if a != b)
    if n_renamed:
        print(f"    ℹ {n_renamed} trafo_keys renombrados para unicidad (sufijo _A/_B)")

    for (_, row), tkey in zip(trafos.iterrows(), trafo_keys_uniq):
        bus_i_id = int(row['bus_i'])
        bus_j_id = int(row['bus_j'])

        if bus_i_id not in all_bus_ids or bus_j_id not in all_bus_ids:
            n_skip_trafo += 1
            missing = []
            if bus_i_id not in all_bus_ids: missing.append(f"bus_i={bus_i_id}")
            if bus_j_id not in all_bus_ids: missing.append(f"bus_j={bus_j_id}")
            print(f"    ⚠ Trafo omitido: {tkey}  ({', '.join(missing)})")
            continue

        bus_i_name = id_to_name[bus_i_id]
        bus_j_name = id_to_name[bus_j_id]

        r_pu   = safe_float(row['r_pu'])
        x_pu   = safe_float(row['x_pu'])
        s_nom  = safe_float(row['sbase_mva'], default=100.0)

        n.add(
            "Transformer",
            tkey,
            bus0  = bus_i_name,
            bus1  = bus_j_name,
            r     = r_pu,
            x     = x_pu,
            s_nom = s_nom,
        )
        n_trafos += 1

    print(f"    Transformadores agregados : {n_trafos}")
    if n_skip_trafo:
        print(f"    ⚠ Omitidos               : {n_skip_trafo}")

    # ==========================================================
    # RESUMEN DE LA RED
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"RESUMEN RED 500 kV — PyPSA")
    print(f"{'='*60}")
    print(f"  Buses           : {len(n.buses)}")
    print(f"    500 kV        : {(n.buses['v_nom'] == 500).sum()}")
    print(f"    Secundarios   : {(n.buses['v_nom'] != 500).sum()}")
    print(f"  Lineas          : {len(n.lines)}")
    print(f"  Transformadores : {len(n.transformers)}")

    # Distribucion de tensiones en buses
    print(f"\n  Distribucion de v_nom:")
    for vnom, grp in n.buses.groupby('v_nom'):
        print(f"    {int(vnom):>5} kV : {len(grp)} buses")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    n.export_to_netcdf(OUTPUT_FILE)

    print(f"\n✔ {OUTPUT_FILE}")
    print(f"\nPara verificar en Python:")
    print(f"    import pypsa")
    print(f"    n = pypsa.Network('{OUTPUT_FILE}')")
    print(f"    print(n)")


if __name__ == "__main__":
    main()
