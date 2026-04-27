"""
08_build_pypsa_network.py
Builds the PyPSA Network object for the 500 kV SADI network and exports it to .nc.

Inputs:
    data/network_500kv/buses_final.csv        (script 05 — all buses)
    data/network_500kv/lines_500kv_final.csv  (script 06 — lines with geometry)
    data/network_500kv/trafos_500kv_raw.csv   (script 03 — transformers)

Outputs:
    networks/network_500kv.nc
    data/network_500kv/fusion_map.csv   (child_bus_name -> root_bus_name mapping
                                         for primary buses merged via bus section
                                         couplers; empty file if no merges occur)

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/08_build_pypsa_network.py

Modeling decisions:
    - Bus section couplers (series_compensator with r=0) merged in memory before building.
    - Impedances from PSS/E in pu (Sbase=100 MVA), converted to physical units per line:
        Z_base = baskv_kv(bus_i)² / S_base
    - s_nom from ratea_mva (MVA); NaN -> s_nom=0 (no limit)
    - 3W transformers already decomposed into 2W from script 03
    - tap_ratio from WINDV of 500 kV winding (script 03)
    - PSS/E base case voltages stored in n.buses for warm start (used by script 12c)
    - Brazil interconnection controlled by INCLUDE_BRAZIL_INTERCONNECTION flag
    - Series compensators (x < 0) added as Line with negative x
    - Lines with match_status='pending_bus' skipped (terminal bus missing)
    - Lines with ratea_mva=NaN: s_nom=0 (no thermal limit)
    - Duplicate trafo_keys (3W decomposed) resolved with suffix _A, _B
    - Brazil Link: import only (p_min_pu=0), free for the solver
    - Lines where merging collapsed both terminals to the same bus: skipped
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
import numpy as np
import pypsa

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])

DATA_DIR   = REPO_DIR / "data/network_500kv"
OUTPUT_DIR = REPO_DIR / "networks"

BUSES_FILE       = DATA_DIR / "buses_final.csv"
LINES_FILE       = DATA_DIR / "lines_500kv_final.csv"
TRAFOS_FILE      = DATA_DIR / "trafos_500kv_raw.csv"
OUTPUT_FILE      = OUTPUT_DIR / "network_500kv.nc"
FUSION_MAP_FILE  = DATA_DIR / "fusion_map.csv"

# PSS/E system base — confirmed in .raw header (line 2, SBASE field)
S_BASE_MVA = 100.0

# Argentina–Brazil interconnection
# If True: adds GARABI bus, BRASIL bus, RINCON-GARABI line and import Link
INCLUDE_BRAZIL_INTERCONNECTION = True

_ZBASE_500 = (500.0 ** 2) / S_BASE_MVA
BRAZIL_INTERCONNECTION = {
    'r_line'       : 1.24e-3  * _ZBASE_500,
    'x_line'       : 1.493e-2 * _ZBASE_500,
    'b_line'       : 1.38425  / _ZBASE_500,
    's_nom_line'   : 1299.0,
    'len_km'       : 128.65,
    'p_nom_link'   : 2200.0,
    'marginal_cost': 110.0,
    'lat_garabi'   : -28.2545246970571,
    'lon_garabi'   : -55.6718056442151,
}


# =============================================================================
# HELPERS
# =============================================================================

def safe_float(val, default=0.0):
    """Converts to float, returns default if NaN or unparseable."""
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def make_unique_keys(keys):
    """
    Resolves duplicate keys by appending suffix _A, _B, _C...
    Returns a list of unique keys of the same length.
    """
    from collections import Counter
    count  = Counter()
    seen   = Counter()
    result = []
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
    print("08_build_pypsa_network.py -- build PyPSA Network 500 kV")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    buses  = pd.read_csv(BUSES_FILE)
    lines  = pd.read_csv(LINES_FILE)
    trafos = pd.read_csv(TRAFOS_FILE)

    # Map bus_id -> bus_name (to resolve lines and transformers)
    id_to_name  = dict(zip(buses['bus_id'].astype(int), buses['bus_name']))
    bus_vnom    = dict(zip(buses['bus_id'].astype(int), buses['baskv_kv'].astype(float)))
    all_bus_ids = set(buses['bus_id'].astype(int))

    # ==========================================================
    # CREATE NETWORK
    # ==========================================================
    n = pypsa.Network()
    n.name = "SADI 500kV"
    n.set_snapshots(pd.DatetimeIndex(["2024-01-01"]))
    print(f"\n✔ Network created")

    # ==========================================================
    # [1] ADD BUSES
    # ==========================================================
    print(f"\n[1] Adding buses...")
    n_added_buses = 0
    n_no_coord    = 0

    for _, row in buses.iterrows():
        lat = row['lat'] if pd.notna(row['lat']) else np.nan
        lon = row['lon'] if pd.notna(row['lon']) else np.nan
        if pd.isna(lat) or pd.isna(lon):
            n_no_coord += 1

        n.add(
            "Bus",
            row['bus_name'],
            v_nom   = float(row['baskv_kv']),
            x       = lon,
            y       = lat,
            carrier = "AC",
        )
        n_added_buses += 1

    # Store PSS/E base case voltage profile in n.buses (warm start for script 12c)
    buses_indexed = buses.set_index('bus_name')
    n.buses['v_mag_pu_psse']  = buses_indexed['vm_pu'].reindex(n.buses.index).fillna(1.0)
    n.buses['v_ang_deg_psse'] = buses_indexed['va_deg'].reindex(n.buses.index).fillna(0.0)

    print(f"    Buses added       : {n_added_buses}")
    if n_no_coord:
        print(f"    ⚠ No coordinates  : {n_no_coord} (added anyway)")

    # ==========================================================
    # [1b] MERGE BUS SECTION COUPLERS
    # Series compensators with r=0 are bus section couplers — they
    # connect internal busbars of the same physical substation and
    # have infinite admittance, making the Newton-Raphson Jacobian
    # singular. Merged to the group representative (lowest bus_id)
    # before adding lines and transformers.
    # CSVs are not modified — merging is in memory only.
    # ==========================================================
    print(f"\n[1b] Merging bus section couplers (series_compensator with r=0)...")

    couplers = lines[
        (lines['element_type'] == 'series_compensator') &
        (lines['r_pu'] == 0.0)
    ]

    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def is_clean_name(name):
        """True if bus name has no '.' or '-' characters."""
        return "." not in name and "-" not in name

    def pick_root(a, b):
        """Returns the preferred root among two bus_id strings.
        Primary criterion : prefer the bus whose name has no '.' or '-'.
        Secondary (tiebreak): lower bus_id wins (matches original behavior)."""
        name_a = id_to_name.get(int(a), "")
        name_b = id_to_name.get(int(b), "")
        clean_a = is_clean_name(name_a)
        clean_b = is_clean_name(name_b)
        if clean_a and not clean_b:
            return a
        if clean_b and not clean_a:
            return b
        try:
            return a if int(a) <= int(b) else b
        except (ValueError, TypeError):
            return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        root = pick_root(ra, rb)
        if root == ra:
            parent[rb] = ra
        else:
            parent[ra] = rb

    for _, row in couplers.iterrows():
        union(str(row['bus_i']), str(row['bus_j']))

    all_bus_id_strs = set(str(bid) for bid in all_bus_ids)
    fusion_map_ids  = {b: find(b) for b in all_bus_id_strs if find(b) != b}

    fusion_map = {}
    for child_id_str, root_id_str in fusion_map_ids.items():
        child_name = id_to_name.get(int(child_id_str))
        root_name  = id_to_name.get(int(root_id_str))
        if child_name and root_name:
            fusion_map[child_name] = root_name

    print(f"    Couplers detected : {len(couplers)}")
    print(f"    Merged buses      : {len(fusion_map)}")
    for child, root in sorted(fusion_map.items()):
        print(f"      {child:<20} -> {root}")

    # Persist fusion_map for downstream scripts that need to resolve
    # pre-merge bus names (e.g. 20A_simplify_network.py reading parent_bus_id
    # from buses_final.csv, which still references merged primaries).
    if fusion_map:
        fusion_df = pd.DataFrame(
            sorted(fusion_map.items()),
            columns=["child_bus_name", "root_bus_name"],
        )
    else:
        fusion_df = pd.DataFrame(columns=["child_bus_name", "root_bus_name"])
    fusion_df.to_csv(FUSION_MAP_FILE, index=False)
    print(f"    fusion_map saved  : {FUSION_MAP_FILE}")

    for child_name in fusion_map:
        if child_name in n.buses.index:
            n.remove("Bus", child_name)
    print(f"    Buses removed from network : {len(fusion_map)}")

    def resolve(bus_name):
        """Returns the representative bus after merging."""
        return fusion_map.get(bus_name, bus_name)

    # ==========================================================
    # [2] ADD LINES AND SERIES COMPENSATORS
    # ==========================================================
    print(f"\n[2] Adding lines and series compensators...")
    n_lines        = 0
    n_comps        = 0
    n_skip_bus     = 0
    n_skip_coupler = 0

    for _, row in lines.iterrows():
        bus_i_id = int(row['bus_i'])
        bus_j_id = int(row['bus_j'])

        if bus_i_id not in all_bus_ids or bus_j_id not in all_bus_ids:
            n_skip_bus += 1
            continue

        if row['match_status'] == 'pending_bus':
            n_skip_bus += 1
            continue

        # Skip bus section couplers (already resolved by merging)
        if row['element_type'] == 'series_compensator' and safe_float(row['r_pu']) == 0.0:
            n_skip_coupler += 1
            continue

        bus_i_name = resolve(id_to_name[bus_i_id])
        bus_j_name = resolve(id_to_name[bus_j_id])

        # Skip if merging collapsed both terminals to the same bus
        if bus_i_name == bus_j_name:
            n_skip_coupler += 1
            continue

        vbase  = bus_vnom[bus_i_id]
        z_base = (vbase ** 2) / S_BASE_MVA

        r_ohm = safe_float(row['r_pu']) * z_base
        x_ohm = safe_float(row['x_pu']) * z_base
        b_s   = safe_float(row['b_pu']) / z_base
        s_nom = safe_float(row['ratea_mva'], default=0.0)

        n.add(
            "Line",
            row['line_key'],
            bus0  = bus_i_name,
            bus1  = bus_j_name,
            r     = r_ohm,
            x     = x_ohm,
            b     = b_s,
            s_nom = s_nom,
        )

        if row['element_type'] == 'series_compensator':
            n_comps += 1
        else:
            n_lines += 1

    print(f"    Lines added            : {n_lines}")
    print(f"    Series compensators    : {n_comps}")
    if n_skip_coupler:
        print(f"    Couplers skipped       : {n_skip_coupler} (merged in [1b])")
    if n_skip_bus:
        print(f"    ⚠ Skipped (missing bus or pending_bus): {n_skip_bus}")

    # ==========================================================
    # [3] ADD TRANSFORMERS
    # ==========================================================
    print(f"\n[3] Adding transformers...")
    n_trafos     = 0
    n_skip_trafo = 0

    if 'tap_ratio' not in trafos.columns:
        print(f"    ⚠ tap_ratio column missing in {TRAFOS_FILE}")
        print(f"      Regenerate trafos_500kv_raw.csv by running the updated script 03.")
        print(f"      Assuming tap_ratio=1.0 for all transformers (suboptimal result).")

    trafo_keys_raw  = list(trafos['trafo_key'])
    trafo_keys_uniq = make_unique_keys(trafo_keys_raw)
    n_renamed = sum(1 for a, b in zip(trafo_keys_raw, trafo_keys_uniq) if a != b)
    if n_renamed:
        print(f"    ℹ {n_renamed} trafo_keys renamed for uniqueness (suffix _A/_B)")

    for (_, row), tkey in zip(trafos.iterrows(), trafo_keys_uniq):
        bus_i_id = int(row['bus_i'])
        bus_j_id = int(row['bus_j'])

        if bus_i_id not in all_bus_ids or bus_j_id not in all_bus_ids:
            n_skip_trafo += 1
            missing = []
            if bus_i_id not in all_bus_ids: missing.append(f"bus_i={bus_i_id}")
            if bus_j_id not in all_bus_ids: missing.append(f"bus_j={bus_j_id}")
            print(f"    ⚠ Transformer skipped: {tkey}  ({', '.join(missing)})")
            continue

        bus_i_name = resolve(id_to_name[bus_i_id])
        bus_j_name = resolve(id_to_name[bus_j_id])

        if bus_i_name == bus_j_name:
            n_skip_trafo += 1
            continue

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

    print(f"    Transformers added : {n_trafos}")
    if n_skip_trafo:
        print(f"    ⚠ Skipped          : {n_skip_trafo}")

    tap_off = (trafos.loc[trafos['trafo_key'].isin(trafo_keys_raw), 'tap_ratio'] != 1.0).sum()
    print(f"    Transformers with tap != 1.0 : {tap_off}")

    # ==========================================================
    # NETWORK SUMMARY
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"NETWORK SUMMARY — PyPSA 500 kV")
    print(f"{'='*60}")
    print(f"  Buses           : {len(n.buses)}")
    print(f"    500 kV        : {(n.buses['v_nom'] == 500).sum()}")
    print(f"    Secondary     : {(n.buses['v_nom'] != 500).sum()}")
    print(f"  Lines           : {len(n.lines)}")
    print(f"  Transformers    : {len(n.transformers)}")

    print(f"\n  Voltage distribution (v_nom):")
    for vnom, grp in n.buses.groupby('v_nom'):
        print(f"    {vnom:>7.1f} kV : {len(grp)} buses")

    vm_range = n.buses['v_mag_pu_psse']
    print(f"\n  PSS/E voltage profile stored in buses (warm start for script 12c):")
    print(f"    v_mag_pu_psse range : [{vm_range.min():.4f}, {vm_range.max():.4f}]")

    # ==========================================================
    # [OPT] BRAZIL INTERCONNECTION
    # ==========================================================
    if INCLUDE_BRAZIL_INTERCONNECTION:
        print(f"\n[OPT] Adding Argentina–Brazil interconnection...")
        ic = BRAZIL_INTERCONNECTION

        n.add("Bus", "GARABI",
              v_nom=500.0, carrier="AC",
              x=ic['lon_garabi'], y=ic['lat_garabi'])

        n.add("Bus", "BRASIL",
              v_nom=500.0, carrier="AC",
              x=ic['lon_garabi'], y=ic['lat_garabi'])

        rincon_name = id_to_name.get(5002, "RINCON")
        n.add("Line", "RINCON-GARABI-1",
              bus0  = rincon_name,
              bus1  = "GARABI",
              r     = ic['r_line'],
              x     = ic['x_line'],
              b     = ic['b_line'],
              s_nom = ic['s_nom_line'])

        n.add("Link", "importacion_brasil",
              bus0          = "BRASIL",
              bus1          = "GARABI",
              p_nom         = ic['p_nom_link'],
              p_min_pu      = 0.0,
              marginal_cost = ic['marginal_cost'])

        print(f"    ✔ GARABI bus, BRASIL bus, RINCON-GARABI line and import Link added")

    # ==========================================================
    # EXPORT
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    n.export_to_netcdf(OUTPUT_FILE)

    print(f"\n✔ {OUTPUT_FILE}")
    print(f"\nTo verify in Python:")
    print(f"    import pypsa")
    print(f"    n = pypsa.Network('{OUTPUT_FILE}')")
    print(f"    print(n)")
    print("Next: 09_map_generators.py")


if __name__ == "__main__":
    main()
