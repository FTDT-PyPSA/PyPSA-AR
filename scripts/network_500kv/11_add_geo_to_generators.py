"""
11_add_geo_to_generators.py
Assigns GeoSADI coordinates and name to each generator from generators_mapped.csv.

Inputs:
    data/network_500kv/generators_mapped.csv
    data/network_500kv/buses_final.csv
    Official data/GEOSADI/CSV/centrales_electricas.csv  (external — download from GitHub Releases, place in external_data_dir/GEOSADI/CSV/)

Outputs:
    data/network_500kv/generators_readypypsa.csv
        One row per generator. Have geosadi_name AND bus_conexion500kv resolved.
        Direct candidates to enter PyPSA.
        Script 12 merges these with resolved pending rows to build generators_final.csv.

    data/network_500kv/generators_pendingmanualpypsa.csv
        Generators missing geosadi_name, bus_conexion500kv, or both.
        Column 'missing': 'geo' / 'bus' / 'both'
        Column 'Comments': empty — fill manually with decision taken
            (e.g. 'internal grid ALUAR, not in PyPSA').

        To resolve pending entries:
            - If geosadi_name is filled in: set geo_match = 'manual'
            - If bus_conexion500kv_manual is filled in: set match_type = 'manual'
            - If the plant is not in PyPSA: fill only Comments

        Once completed and renamed to generators_manualpypsa.csv,
        script 12 joins readypypsa + resolved pending rows -> generators_final.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/11_add_geo_to_generators.py

============================================================
GEOGRAPHIC MATCHING
============================================================

The first 4 characters of bus_name_origen (PSS/E) are compared against
the first 4 characters of the Nemo field in centrales_electricas.csv.

Single candidate, or multiple resolved by type -> geo_match='exact'.
Multiple candidates not resolvable by type    -> geo_match='review'.
No candidates                                 -> geo_match='no_match'.

For ambiguous cases, the  PREFERRED_NEMO dictionary assigns
bus_name_origen -> GeoSADI Nemo explicitly.

CARRIER -> GEOSADI TYPE INDEX:
    ocgt         -> TG        steam        -> TV
    hydro        -> HI, HR    diesel       -> DI
    ccgt         -> CC        nuclear      -> NU
    wind         -> EO        solar        -> FV
    biogas       -> BG        biomass      -> BM
    battery      -> BESS      pumped_hydro -> HB

============================================================
CARRIER OVERRIDES
============================================================

GeoSADI type HB -> carrier = 'pumped_hydro'
    Only case in Argentina: Rio Grande (750 MW).

GeoSADI type VG -> accepted if PSS/E carrier in {ocgt, steam, ccgt}.
    Otherwise flagged as 'VG_review' and goes to pending.

============================================================
SEPARATION CRITERIA
============================================================

generators_readypypsa:
    geo_match == 'exact'  AND  bus_conexion500kv not empty

generators_pendingmanualpypsa.csv (one row per generator):
    Everything else. Columns to fill manually:
        geosadi_name           -> if geo missing, set geo_match='manual'
        bus_conexion500kv_manual -> if bus missing, set match_type='manual'
        Comments              -> always (e.g. 'internal grid ALUAR, not in PyPSA')
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

GENERATORS_FILE = REPO_DIR / "data/network_500kv/generators_mapped.csv"
POWER_PLANTS_FILE     = EXTERNAL_DIR / "GEOSADI/CSV/centrales_electricas.csv"
BUSES_FILE      = REPO_DIR / "data/network_500kv/buses_final.csv"
OUTPUT_DIR      = REPO_DIR / "data/network_500kv"
OUTPUT_READY    = OUTPUT_DIR / "generators_readypypsa.csv"
OUTPUT_PENDING  = OUTPUT_DIR / "generators_pendingmanualpypsa.csv"

CARRIER_TO_TYPE = {
    'ocgt'        : ['TG'],
    'steam'       : ['TV'],
    'hydro'       : ['HI', 'HR'],
    'diesel'      : ['DI'],
    'ccgt'        : ['CC'],
    'nuclear'     : ['NU'],
    'wind'        : ['EO'],
    'solar'       : ['FV'],
    'biogas'      : ['BG'],
    'biomass'     : ['BM'],
    'battery'     : ['BESS'],
    'pumped_hydro': ['HB'],
}

VG_VALID_CARRIERS = {'ocgt', 'steam', 'ccgt'}

TYPO_OVERRIDE = {
    'HB': 'pumped_hydro',
}

# Explicit bus_name_origen -> GeoSADI Nemo mapping for ambiguous cases
# Salto Grande (SGDE): Argentine side -> SGDEHIAR, Uruguayan side -> SGDEHIUR
PREFERRED_NEMO = {
    'SGDEHI01': 'SGDEHIAR',
    'SGDEHI02': 'SGDEHIAR',
    'SGDEHI03': 'SGDEHIAR',
    'SGDEHI04': 'SGDEHIAR',
    'SGDEHI05': 'SGDEHIAR',
    'SGDEHI06': 'SGDEHIAR',
    'SGDEHI13': 'SGDEHIAR',
    'SGDEHI07': 'SGDEHIUR',
    'SGDEHI08': 'SGDEHIUR',
    'SGDEHI09': 'SGDEHIUR',
    'SGDEHI10': 'SGDEHIUR',
    'SGDEHI11': 'SGDEHIUR',
    'SGDEHI12': 'SGDEHIUR',
    'SGDEHI14': 'SGDEHIUR',
}


# =============================================================================
# GEOGRAPHIC MATCHING
# =============================================================================

def build_nemo_index(power_plants):
    power_plants = power_plants.copy()
    power_plants['nemo4'] = power_plants['Nemo'].str[:4].str.upper()
    nemo4_index     = {}
    nemo_full_index = {}
    for _, row in power_plants.iterrows():
        nemo4_index.setdefault(row['nemo4'], []).append(row)
        nemo_full_index[str(row['Nemo']).strip().upper()] = row
    return nemo4_index, nemo_full_index


def resolve_match(bus_name_origen, carrier, nemo4_index, nemo_full_index):
    bus_name_clean = bus_name_origen.strip().upper()

    if bus_name_clean in PREFERRED_NEMO:
        nemo_key = PREFERRED_NEMO[bus_name_clean].upper()
        if nemo_key in nemo_full_index:
            return nemo_full_index[nemo_key], 'exact'

    prefix4    = bus_name_clean[:4]
    candidates = nemo4_index.get(prefix4, [])

    if not candidates:
        return None, 'no_match'
    if len(candidates) == 1:
        return candidates[0], 'exact'

    valid_types = CARRIER_TO_TYPE.get(carrier, [])
    filtered = [r for r in candidates if r['Tipo'] in valid_types]
    if len(filtered) == 1:
        return filtered[0], 'exact'

    return None, 'review'


def has_bus(bus_con):
    if bus_con is None:
        return False
    s = str(bus_con).strip()
    return s != '' and s.lower() != 'nan'


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("11_add_geo_to_generators.py -- assign GeoSADI coordinates")
    print("=" * 60)

    for f in [GENERATORS_FILE, POWER_PLANTS_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    gens      = pd.read_csv(GENERATORS_FILE)
    power_plants = pd.read_csv(POWER_PLANTS_FILE)
    buses_df  = pd.read_csv(BUSES_FILE)

    print(f"Generators loaded             : {len(gens)}")
    print(f"GeoSADI plants                : {len(power_plants)}")
    print(f"Model buses                   : {len(buses_df)}")

    nemo4_index, nemo_full_index = build_nemo_index(power_plants)

    print(f"\nRunning geographic matching + manual resolution...")

    geosadi_names  = []
    lats             = []
    lons             = []
    geo_matches      = []
    carriers_out     = []
    match_types_out  = []
    bus_con_out      = []
    bus_con_name_out = []

    n_exact = n_no_match = n_review = 0
    n_override_hb = n_vg_review = 0
    warnings = []

    for _, row in gens.iterrows():
        bus_name   = str(row['bus_name_origen'])
        carrier    = str(row['carrier'])
        match_type = str(row['match_type'])
        bus_con    = row['bus_conexion500kv']
        bus_con_nm = row['bus_conexion500kv_name']

        geo_row, status = resolve_match(bus_name, carrier, nemo4_index, nemo_full_index)

        if geo_row is None:
            name = ''
            lat    = np.nan
            lon    = np.nan
            if status == 'no_match':
                n_no_match += 1
            else:
                n_review += 1
                candidatos = nemo4_index.get(bus_name.strip().upper()[:4], [])
                warnings.append(
                    f"  review: {row['gen_key']}  bus={bus_name.strip()}"
                    f"  carrier={carrier}  candidates={[r['Nemo'] for r in candidatos]}"
                )
        else:
            name = geo_row['Nombre']
            lat    = geo_row['latitude']
            lon    = geo_row['longitude']
            tipo   = geo_row['Tipo']
            n_exact += 1
            if tipo in TYPO_OVERRIDE:
                carrier = TYPO_OVERRIDE[tipo]
                n_override_hb += 1
            elif tipo == 'VG':
                if carrier not in VG_VALID_CARRIERS:
                    warnings.append(
                        f"  VG_review: {row['gen_key']}  bus={bus_name.strip()}"
                        f"  carrier_psse={carrier}  plant={name}"
                    )
                    carrier = 'VG_review'
                    n_vg_review += 1

        geosadi_names.append(name)
        lats.append(lat)
        lons.append(lon)
        geo_matches.append(status)
        carriers_out.append(carrier)
        match_types_out.append(match_type)
        bus_con_out.append(bus_con)
        bus_con_name_out.append(bus_con_nm)

    df_out = gens.copy()
    df_out['carrier']                = carriers_out
    df_out['geosadi_name']           = geosadi_names
    df_out['lat']                    = lats
    df_out['lon']                    = lons
    df_out['geo_match']              = geo_matches
    df_out['match_type']             = match_types_out
    df_out['bus_conexion500kv']      = bus_con_out
    df_out['bus_conexion500kv_name'] = bus_con_name_out

    COLS = [
        'gen_key', 'bus_id_origen', 'bus_name_origen', 'geosadi_name', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'lat', 'lon',
        'geo_match', 'match_type',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_jumps', 'path',
    ]
    df_out = df_out[COLS]

    # ==========================================================
    # SPLIT ready vs pending
    # ==========================================================
    mask_geo     = df_out['geo_match'] == 'exact'
    mask_bus     = df_out['bus_conexion500kv'].apply(has_bus)
    mask_carrier = df_out['carrier'] != 'VG_review'

    df_ready       = df_out[mask_geo & mask_bus & mask_carrier].copy()
    df_pending_ind = df_out[~(mask_geo & mask_bus & mask_carrier)].copy()

    def get_missing(row):
        has_g = row['geo_match'] == 'exact'
        has_b = has_bus(row['bus_conexion500kv'])
        if not has_g and not has_b: return 'both'
        if not has_g: return 'geo'
        return 'bus'

    df_pending_ind['missing'] = df_pending_ind.apply(get_missing, axis=1)

    df_pending = df_pending_ind[[
        'gen_key', 'bus_id_origen', 'bus_name_origen', 'geosadi_name', 'missing', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'lat', 'lon',
        'geo_match', 'match_type',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_jumps', 'path',
    ]].copy()
    df_pending['Comments'] = ''
    df_pending = df_pending.sort_values('pt_mw', ascending=False)

    # ==========================================================
    # SUMMARY
    # ==========================================================
    total = len(df_out)
    print(f"\n{'='*60}")
    print(f"GEOGRAPHIC MATCHING")
    print(f"{'='*60}")
    print(f"  exact    : {n_exact:>4}  ({n_exact/total*100:.1f}%)")
    print(f"  no_match : {n_no_match:>4}  ({n_no_match/total*100:.1f}%)")
    print(f"  review   : {n_review:>4}  ({n_review/total*100:.1f}%)")

    print(f"\n{'='*60}")
    print(f"CARRIER OVERRIDES")
    print(f"{'='*60}")
    print(f"  HB -> pumped_hydro : {n_override_hb} generators")
    print(f"  VG_review         : {n_vg_review} generators")

    if warnings:
        print(f"\n  Warnings ({len(warnings)}):")
        for w in warnings:
            print(w)

    print(f"\n{'='*60}")
    print(f"OUTPUT SPLIT")
    print(f"{'='*60}")
    mw_ready   = df_ready[df_ready['pt_mw'] < 9000]['pt_mw'].sum()
    mw_pending = df_pending[df_pending['pt_mw'] < 9000]['pt_mw'].sum()
    print(f"  generators_readypypsa        : {len(df_ready):>4} generators  {mw_ready:>10,.1f} MW")
    print(f"  generators_pendingmanualpypsa: {len(df_pending):>4} generators  {mw_pending:>10,.1f} MW")

    print(f"\n  Pending by carrier:")
    for carrier, grp in df_pending.groupby('carrier'):
        mw = grp[grp['pt_mw'] < 9000]['pt_mw'].sum()
        print(f"    {carrier:<15}: {len(grp):>4} units   {mw:>10,.1f} MW")

    print(f"\n{'='*60}")
    print(f"BY CARRIER — readypypsa (stat=1, pt < 9999)")
    print(f"{'='*60}")
    activos = df_ready[(df_ready['stat'] == 1) & (df_ready['pt_mw'] < 9990)]
    for carrier, grp in activos.groupby('carrier'):
        print(f"  {carrier:<15}: {len(grp):>4} units   {grp['pt_mw'].sum():>10,.1f} MW")

    # ==========================================================
    # EXPORT
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_ready.to_csv(OUTPUT_READY, index=False)
    df_pending.to_csv(OUTPUT_PENDING, index=False)
    print(f"\n✔ {OUTPUT_READY}    ({len(df_ready)} rows)")
    print(f"✔ {OUTPUT_PENDING}  ({len(df_pending)} rows)")
    print("Next: 12_build_generators_final.py")


if __name__ == "__main__":
    main()
