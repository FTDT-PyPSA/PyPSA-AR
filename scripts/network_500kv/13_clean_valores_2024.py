"""
13_clean_valores_2024.py
Cleans and validates VALORES_2024.csv (CAMMESA hourly generation data).
Produces valores_2024_clean.csv — the reliable file used by all downstream
scripts (14, 15, 17, 18).

Input:
    Official data/VALORES_2024.csv  (external — download from GitHub Releases, place in external_data_dir/)
        Hourly generation data 2024 from the Argentine Wholesale Electricity Market (MEM).
        ~8.8 million rows. One row per unit (GRUPO) per hour.
        Separator: semicolon. Encoding: latin-1.

Output:
    Official data/valores_2024_clean.csv  (external — download from GitHub Releases, place in external_data_dir/)
        Only rows from year 2024 (original file also contains 2025 data).
        Same row structure as input (no 2024 rows removed).
        Normalized columns + datetime column + flag_outlier column.

Transformations applied:
    1. Only physically/operationally relevant columns are read.
       POT_RECONOC (economic settlement field) is excluded.

    2. Date normalization:
       Formats detected in the original file:
         - 'd/mm/yy'         (days 1-9, January/May/June)
         - 'dd/mm/yy'        (rest of January/May/June)
         - 'dd/mm/yy 00:00'  (February to December)
       All converted to 'dd/mm/yyyy' (zero-padded day, 4-digit year).

    3. Year filter: all rows whose normalized date does not belong to 2024
       are discarded. The original file contains data through June 2025.

    4. datetime column added = date + hour (full timestamp).
       HORA (hour) follows CAMMESA convention (1 to 24).
       Conversion: datetime = date + (hour - 1) hours.
       Example: date=01/01/2024, hour=1  -> 2024-01-01 00:00:00
                date=01/01/2024, hour=24 -> 2024-01-01 23:00:00

    5. Outlier detection per unit (GRUPO):
       flag_outlier = True if any of these conditions apply:
         a. energy_mwh  < 0
         b. available_capacity_mw < 0
         c. energy_mwh  > 99.9th percentile of energy_mwh  for that unit in the year
         d. available_capacity_mw > 99.9th percentile of available_capacity_mw for that unit
       Rows are NOT removed. The flag lets downstream scripts decide how to handle each case.

Run from the repository root (pypsa-ar-base/):
        python scripts/network_500kv/13_clean_valores_2024.py
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
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

VALORES_FILE = EXTERNAL_DIR / "VALORES_2024.csv"
OUTPUT_FILE  = EXTERNAL_DIR / "valores_2024_clean.csv"

# Rows per chunk — reduce if memory issues arise
CHUNK_SIZE = 500_000

# Columns to read from the original file
# POT_RECONOC (economic settlement field) is excluded
COLS_READ = [
    'FECHA', 'HORA', 'GRUPO', 'TIPO', 'Central', 'Region',
    'ENERGIA', 'POT_DISP', 'ENERG_OPERADA', 'POT_DISP_GN', 'PIND',
]

# Output column names (translated from CAMMESA originals)
COL_RENAME = {
    'FECHA'        : 'date',
    'HORA'         : 'hour',
    'GRUPO'        : 'unit',
    'TIPO'         : 'carrier',
    'Central'      : 'code',
    'Region'       : 'region',
    'ENERGIA'      : 'energy_mwh',
    'POT_DISP'     : 'available_capacity_mw',
    'ENERG_OPERADA': 'operated_energy_mwh',
    'POT_DISP_GN'  : 'gas_available_capacity_mw',
    'PIND'         : 'PIND',
}

# TIPO values translated from CAMMESA Spanish to English
CARRIER_RENAME = {
    'Biogas'             : 'biogas',
    'Biomasa'            : 'biomass',
    'Ciclos Combinados'  : 'ccgt',
    'Eolica'             : 'wind',
    'Hidraulica'         : 'hydro',
    'Hidraulica renovable': 'hydro_renewable',
    'Motor Diesel'       : 'diesel',
    'Nuclear'            : 'nuclear',
    'Solar'              : 'solar',
    'Turbina a gas'      : 'ocgt',
    'Turbovapor'         : 'steam',
    'XM'                 : 'international_import',
}

# Output columns (final order)
COLS_OUTPUT = [
    'date', 'hour', 'datetime', 'unit', 'carrier', 'code', 'region',
    'energy_mwh', 'available_capacity_mw', 'operated_energy_mwh',
    'gas_available_capacity_mw', 'PIND',
    'flag_outlier',
]

# Percentile threshold for outlier detection
OUTLIER_PERCENTILE = 99.9

# Units excluded from the clean file.
# YACYHIPY: Paraguayan side of Yacyreta — not part of the Argentine model.
UNITS_EXCLUDE = {'YACYHIPY'}

# Binational plants: CAMMESA reports total plant output.
# Factor applied before writing to output to keep only the Argentine share.
# SGDE (Salto Grande): Argentina shares the plant with Uruguay at 50%.
BINATIONAL_FACTOR = {'SGDE': 0.5}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_date(series):
    """
    Converts all date formats in the file to 'dd/mm/yyyy'.

    Input formats:
        'd/mm/yy'        -> '01/01/2024'
        'dd/mm/yy'       -> '01/01/2024'
        'dd/mm/yy 00:00' -> '01/01/2024'
    """
    s = series.str.strip().str.split(' ').str[0]
    parts = s.str.split('/')
    day  = parts.str[0].str.zfill(2)
    month = parts.str[1].str.zfill(2)
    year  = parts.str[2].apply(lambda x: '20' + x if len(str(x)) == 2 else str(x))
    return day + '/' + month + '/' + year


def build_datetime(date_norm, hour):
    """
    Builds timestamp from normalized date and hour(HORA) column (1-24).
    hour=1 -> 00:00:00, hour=24 -> 23:00:00.
    """
    base = pd.to_datetime(date_norm, format='%d/%m/%Y', errors='coerce')
    return base + pd.to_timedelta(hour - 1, unit='h')


# =============================================================================
# PASS 1 — Calculate 99.9th percentiles per unit (2024 rows only)
# =============================================================================

def pass1_percentiles():
    """
    Reads the file in chunks accumulating energy_mwh and available_capacity_mw
    values per unit, using only 2024 rows.
    Computes the 99.9th annual percentile for each unit.

    Returns two Series indexed by unit:
        p999_energy   — outlier threshold for energy_mwh
        p999_capacity — outlier threshold for available_capacity_mw
    """
    print("\n[PASS 1/2] Computing 99.9th percentiles per unit...")
    print(f"  Chunk size: {CHUNK_SIZE:,} rows")

    accumulator = {}

    reader = pd.read_csv(
        VALORES_FILE,
        sep=';',
        encoding='latin-1',
        usecols=['FECHA', 'GRUPO', 'ENERGIA', 'POT_DISP'],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    n_chunks    = 0
    n_rows      = 0
    n_discarded = 0

    for chunk in reader:
        n_chunks += 1

        # Normalize date and filter 2024 only
        chunk['FECHA'] = normalize_date(chunk['FECHA'])
        mask_2024 = chunk['FECHA'].str.endswith('2024')
        n_discarded += (~mask_2024).sum()
        chunk = chunk[mask_2024]

        n_rows += len(chunk)

        for unit, grp in chunk.groupby('GRUPO'):
            if unit in UNITS_EXCLUDE:
                continue
            if unit not in accumulator:
                accumulator[unit] = {'e': [], 'p': []}
            accumulator[unit]['e'].append(grp['ENERGIA'].values)
            accumulator[unit]['p'].append(grp['POT_DISP'].values)

        if n_chunks % 5 == 0:
            print(f"  ... chunk {n_chunks}, 2024 rows accumulated: {n_rows:,}")

    print(f"  Pass 1 complete — {n_rows:,} 2024 rows, {n_discarded:,} rows discarded (2025)")
    print(f"  Units found: {len(accumulator)}")

    p999_energy   = {}
    p999_capacity = {}

    for unit, vals in accumulator.items():
        e_all = np.concatenate(vals['e'])
        p_all = np.concatenate(vals['p'])
        p999_energy[unit]   = np.nanpercentile(e_all, OUTLIER_PERCENTILE)
        p999_capacity[unit] = np.nanpercentile(p_all, OUTLIER_PERCENTILE)

    return pd.Series(p999_energy), pd.Series(p999_capacity)


# =============================================================================
# PASS 2 — Transform and write output
# =============================================================================

def pass2_transform(p999_energy, p999_capacity):
    """
    Reads the file again in chunks. For each chunk:
        - Normalizes dates
        - Filters 2024 rows only
        - Builds datetime
        - Flags outliers using thresholds from pass 1
        - Renames columns to English
        - Translates carrier values
        - Writes to output (incremental append)

    Returns a dict with statistics for the final report.
    """
    print(f"\n[PASS 2/2] Transforming and writing output...")
    print(f"  Output: {OUTPUT_FILE}")

    reader = pd.read_csv(
        VALORES_FILE,
        sep=';',
        encoding='latin-1',
        usecols=COLS_READ,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    n_chunks       = 0
    n_rows         = 0
    n_outliers     = 0
    n_nat          = 0
    first_chunk    = True
    unique_dates   = set()
    unit_hours     = {}

    cnt_energy_neg  = 0
    cnt_capacity_neg = 0
    cnt_energy_p999  = 0
    cnt_capacity_p999 = 0

    for chunk in reader:
        n_chunks += 1

        # --- Normalize dates ---
        chunk['FECHA'] = normalize_date(chunk['FECHA'])

        # --- Filter 2024 only ---
        chunk = chunk[chunk['FECHA'].str.endswith('2024')].copy()

        # --- Exclude non-Argentine units ---
        chunk = chunk[~chunk['GRUPO'].isin(UNITS_EXCLUDE)].copy()

        if len(chunk) == 0:
            continue

        # --- Apply binational factor (e.g. SGDE x0.5) ---
        for plant_code, factor in BINATIONAL_FACTOR.items():
            mask_bin = chunk['Central'] == plant_code
            if mask_bin.sum() > 0:
                chunk.loc[mask_bin, 'ENERGIA']       *= factor
                chunk.loc[mask_bin, 'POT_DISP']      *= factor
                chunk.loc[mask_bin, 'ENERG_OPERADA'] *= factor
                chunk.loc[mask_bin, 'POT_DISP_GN']   *= factor

        n_rows += len(chunk)
        unique_dates.update(chunk['FECHA'].unique())

        # --- Build datetime ---
        chunk['datetime'] = build_datetime(chunk['FECHA'], chunk['HORA'])
        n_nat += chunk['datetime'].isna().sum()
        chunk['datetime'] = chunk['datetime'].dt.strftime('%d/%m/%Y %H:%M')

        # --- Flag outliers ---
        thr_e  = chunk['GRUPO'].map(p999_energy)
        thr_p  = chunk['GRUPO'].map(p999_capacity)

        crit_a = chunk['ENERGIA']  < 0
        crit_b = chunk['POT_DISP'] < 0
        crit_c = chunk['ENERGIA']  > thr_e
        crit_d = chunk['POT_DISP'] > thr_p

        chunk['flag_outlier'] = crit_a | crit_b | crit_c | crit_d

        cnt_energy_neg    += int(crit_a.sum())
        cnt_capacity_neg  += int(crit_b.sum())
        cnt_energy_p999   += int(crit_c.sum())
        cnt_capacity_p999 += int(crit_d.sum())
        n_outliers        += int(chunk['flag_outlier'].sum())

        # --- Accumulate hours per unit for verification ---
        for unit, grp in chunk.groupby('GRUPO'):
            if unit not in unit_hours:
                unit_hours[unit] = set()
            unit_hours[unit].update(grp['HORA'].unique())

        # --- Rename columns to English ---
        chunk = chunk.rename(columns=COL_RENAME)

        # --- Translate carrier values ---
        chunk['carrier'] = chunk['carrier'].map(CARRIER_RENAME).fillna(chunk['carrier'])

        # --- Write to output incrementally ---
        mode   = 'w' if first_chunk else 'a'
        header = first_chunk
        chunk[COLS_OUTPUT].to_csv(OUTPUT_FILE, index=False, mode=mode, header=header)
        first_chunk = False

        if n_chunks % 5 == 0:
            print(f"  ... chunk {n_chunks}, rows written: {n_rows:,}")

    return {
        'n_rows'           : n_rows,
        'n_outliers'       : n_outliers,
        'n_nat'            : n_nat,
        'unique_dates'     : unique_dates,
        'unit_hours'       : unit_hours,
        'cnt_energy_neg'   : cnt_energy_neg,
        'cnt_capacity_neg' : cnt_capacity_neg,
        'cnt_energy_p999'  : cnt_energy_p999,
        'cnt_capacity_p999': cnt_capacity_p999,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("13_clean_valores_2024.py -- clean VALORES_2024.csv")
    print("=" * 60)

    if not os.path.isfile(VALORES_FILE):
        print(f"[ERROR] File not found:\n  {VALORES_FILE}")
        sys.exit(1)

    # --- Pass 1: compute percentiles ---
    p999_energy, p999_capacity = pass1_percentiles()

    # --- Pass 2: transform and write ---
    stats = pass2_transform(p999_energy, p999_capacity)

    # --- Final report ---
    print(f"\n{'='*60}")
    print("FINAL REPORT")
    print(f"{'='*60}")

    n     = stats['n_rows']
    n_out = stats['n_outliers']
    pct   = 100 * n_out / n if n > 0 else 0

    print(f"\n  Rows written          : {n:,}")
    print(f"  Output columns        : {len(COLS_OUTPUT)}")

    # Unique dates
    n_dates = len(stats['unique_dates'])
    if n_dates == 366:
        print(f"  Unique dates          : {n_dates}  OK (2024 is a leap year)")
    else:
        print(f"  Unique dates          : {n_dates}  [WARNING] expected 366")

    # NaT datetimes
    if stats['n_nat'] == 0:
        print(f"  NaT values            : 0  OK")
    else:
        print(f"  NaT values            : {stats['n_nat']:,}  [WARNING] check dates")

    # Units with incomplete hours
    incomplete_units = {u: h for u, h in stats['unit_hours'].items() if len(h) < 24}
    if incomplete_units:
        print(f"  Units with < 24 h     : {len(incomplete_units)}  [WARNING]")
        for u, h in list(incomplete_units.items())[:5]:
            print(f"    {u}: {sorted(h)}")
    else:
        print(f"  Units with < 24 h     : 0  OK")

    # Outliers
    print(f"\n  Outliers flagged      : {n_out:,}  ({pct:.3f}%)")
    print(f"    energy_mwh < 0              : {stats['cnt_energy_neg']:,}")
    print(f"    available_capacity_mw < 0   : {stats['cnt_capacity_neg']:,}")
    print(f"    energy_mwh > p99.9          : {stats['cnt_energy_p999']:,}")
    print(f"    available_capacity_mw > p99.9: {stats['cnt_capacity_p999']:,}")

    print(f"\n  Output: {OUTPUT_FILE}")
    print("Next: 14_detect_generator_conflicts.py")


if __name__ == "__main__":
    main()
