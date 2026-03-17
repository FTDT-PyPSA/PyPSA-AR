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
    FUSION DE ACOPLADORES DE BARRA:
        Los compensadores serie con r=0 exacto son acopladores de barra
        (bus section couplers): conectan barras internas de la misma
        subestacion fisica y tienen admitancia infinita, lo que hace
        singular el Jacobiano del Newton-Raphson.
        Se detectan automaticamente y se fusionan sus buses al representante
        del grupo (menor bus_id) antes de agregar lineas y trafos.
        Los CSVs originales no se modifican — la fusion es solo en memoria.

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
        - tap_ratio = WINDV del devanado de 500kV (extraido en script 03)
          Si el CSV no tiene la columna (corrida legacy) se asume 1.0 con advertencia.
        - Se omiten trafos con buses ausentes en buses_final.csv
        - Keys duplicados (3W descompuestos) se resuelven agregando sufijo _A, _B

    BUSES — warm start:
        - v_mag_pu_psse y v_ang_deg_psse del caso base PSS/E se guardan como
          atributos adicionales en n.buses y quedan en el .nc.
        - El script 12c los usa para inicializar los setpoints de los generadores PV
          antes del Newton-Raphson, mejorando drasticamente la convergencia.

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
            v_nom   = float(row['baskv_kv']),
            x       = lon,
            y       = lat,
            carrier = "AC",
        )
        n_added_buses += 1

    # Asignar perfil PSS/E directamente al DataFrame de buses
    # (n.add no acepta atributos custom — hay que hacerlo post-loop)
    buses_indexed = buses.set_index('bus_name')
    n.buses['v_mag_pu_psse']  = buses_indexed['vm_pu'].reindex(n.buses.index).fillna(1.0)
    n.buses['v_ang_deg_psse'] = buses_indexed['va_deg'].reindex(n.buses.index).fillna(0.0)

    print(f"    Buses agregados   : {n_added_buses}")
    if n_sin_coord:
        print(f"    ⚠ Sin coordenadas : {n_sin_coord} (agregados igual)")

    # ==========================================================
    # FUSION DE ACOPLADORES DE BARRA
    # Compensadores serie con r=0 exacto no son compensadores reales:
    # son acopladores de barra (bus section couplers) que conectan
    # barras internas de la misma subestacion fisica. Tienen admitancia
    # infinita y hacen singular el Jacobiano del Newton-Raphson.
    # Se fusionan los buses internos al bus principal de cada grupo
    # antes de construir el modelo. Los CSVs originales no se modifican.
    # ==========================================================
    print(f"\n[1b] Fusionando acopladores de barra (series_compensator con r=0)...")

    couplers = lines[
        (lines['element_type'] == 'series_compensator') &
        (lines['r_pu'] == 0.0)
    ]

    # Union-Find para agrupar buses conectados por acopladores
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # El bus de menor id_numerico queda como raiz (favorece al bus principal)
        # Para buses 500kV vs internos, el 500kV tiene nombre mas corto/limpio
        # pero usamos bus_id para ser deterministas
        try:
            if int(ra) > int(rb):
                ra, rb = rb, ra
        except (ValueError, TypeError):
            pass
        parent[rb] = ra

    for _, row in couplers.iterrows():
        union(str(row['bus_i']), str(row['bus_j']))

    # Construir mapa bus_id_str -> bus_id_str del representante
    all_bus_id_strs = set(str(bid) for bid in all_bus_ids)
    fusion_map_ids = {b: find(b) for b in all_bus_id_strs if find(b) != b}

    # Convertir a mapa bus_name -> bus_name usando id_to_name
    fusion_map = {}
    for child_id_str, root_id_str in fusion_map_ids.items():
        child_name = id_to_name.get(int(child_id_str))
        root_name  = id_to_name.get(int(root_id_str))
        if child_name and root_name:
            fusion_map[child_name] = root_name

    print(f"    Acopladores detectados : {len(couplers)}")
    print(f"    Buses fusionados       : {len(fusion_map)}")
    for child, root in sorted(fusion_map.items()):
        print(f"      {child:<20} -> {root}")

    # Eliminar los buses internos del network — ya no tienen razón de existir
    # Sus transformadores y líneas van a apuntar al bus representante
    for child_name in fusion_map:
        if child_name in n.buses.index:
            n.remove("Bus", child_name)
    print(f"    Buses eliminados del network : {len(fusion_map)}")

    def resolve(bus_name):
        """Devuelve el bus representante despues de fusión."""
        return fusion_map.get(bus_name, bus_name)

    # ==========================================================
    # AGREGAR LINEAS
    # ==========================================================
    print(f"\n[2] Agregando lineas y compensadores...")
    n_lines        = 0
    n_comps        = 0
    n_skip_bus     = 0
    n_skip_coupler = 0

    for _, row in lines.iterrows():
        bus_i_id = int(row['bus_i'])
        bus_j_id = int(row['bus_j'])

        # Omitir si alguno de los buses no existe
        if bus_i_id not in all_bus_ids or bus_j_id not in all_bus_ids:
            n_skip_bus += 1
            continue

        # Omitir lineas con bus extremo sin datos
        if row['match_status'] == 'pendiente_bus':
            n_skip_bus += 1
            continue

        # Saltear acopladores de barra (ya resueltos por fusion)
        if row['element_type'] == 'series_compensator' and safe_float(row['r_pu']) == 0.0:
            n_skip_coupler += 1
            continue

        bus_i_name = resolve(id_to_name[bus_i_id])
        bus_j_name = resolve(id_to_name[bus_j_id])

        # Saltear si la fusion colapsó los dos extremos al mismo bus
        if bus_i_name == bus_j_name:
            n_skip_coupler += 1
            continue

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
    if n_skip_coupler:
        print(f"    Acopladores omitidos   : {n_skip_coupler} (fusionados en [1b])")
    if n_skip_bus:
        print(f"    ⚠ Omitidas (bus ausente o pendiente_bus): {n_skip_bus}")

    # ==========================================================
    # AGREGAR TRANSFORMADORES
    # ==========================================================
    print(f"\n[3] Agregando transformadores...")
    n_trafos     = 0
    n_skip_trafo = 0

    # Verificar columna tap_ratio (requiere haber corrido script 03 actualizado)
    if 'tap_ratio' not in trafos.columns:
        print(f"    ⚠ Columna tap_ratio ausente en {TRAFOS_FILE}")
        print(f"      Regenerar trafos_500kv_raw.csv corriendo el script 03 actualizado.")
        print(f"      Se asume tap_ratio=1.0 en todos los trafos (resultado suboptimo).")
        trafos['tap_ratio'] = 1.0

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

        bus_i_name = resolve(id_to_name[bus_i_id])
        bus_j_name = resolve(id_to_name[bus_j_id])

        r_pu      = safe_float(row['r_pu'])
        x_pu      = safe_float(row['x_pu'])
        s_nom     = safe_float(row['sbase_mva'], default=100.0)
        tap_ratio = safe_float(row.get('tap_ratio', 1.0), default=1.0)

        n.add(
            "Transformer",
            tkey,
            bus0      = bus_i_name,
            bus1      = bus_j_name,
            r         = r_pu,
            x         = x_pu,
            s_nom     = s_nom,
            tap_ratio = tap_ratio,
        )
        n_trafos += 1

    print(f"    Transformadores agregados : {n_trafos}")
    if n_skip_trafo:
        print(f"    ⚠ Omitidos               : {n_skip_trafo}")

    tap_off = (trafos.loc[trafos['trafo_key'].isin(trafo_keys_raw), 'tap_ratio'] != 1.0).sum()
    print(f"    Trafos con tap != 1.0    : {tap_off}")

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

    vm_range = n.buses['v_mag_pu_psse']
    print(f"\n  Perfil PSS/E guardado en buses (warm start para 12c):")
    print(f"    v_mag_pu_psse  rango : [{vm_range.min():.4f}, {vm_range.max():.4f}]")

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
