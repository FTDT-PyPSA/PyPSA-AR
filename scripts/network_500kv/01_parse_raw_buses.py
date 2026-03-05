"""
01_parse_raw_buses.py
Extrae buses 500 kV del .raw del SADI y exporta a CSV.

Fuente : C:/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw
Output : C:/Work/pypsa-ar-base/data/network_500kv/buses_500kv_raw.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/01_parse_raw_buses.py

Formato BUS DATA en PSS/E v34:
    I,'NAME',BASKV,IDE,AREA,ZONE,OWNER,VM,VA,NVHI,NVLO,EVHI,EVLO

    IDE=4 (aislado) se excluye -- buses desconectados del sistema, sin ramas activas.
Campos no extraidos:
    NVHI,NVLO,EVHI,EVLO : limites de tension -- todos 1.1/0.9 en este caso base
"""

import os, sys
import pandas as pd

# =============================================================================
# CONFIGURACION
# =============================================================================

RAW_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
OUTPUT_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "buses_500kv_raw.csv")

KV_MIN = 490.0  # incluye 500 kV nominal
KV_MAX = 530.0  # incluye 525 kV que PSS/E asigna a algunos generadores

# Internacionales identificados por AREA segun nomenclatura CAMMESA (del AREA DATA del .raw)
INTERNATIONAL_AREAS = {
    18: "Paraguay",
    19: "Chile (SING)",
    20: "Brasil",
    22: "Bolivia",
    99: "Uruguay",
}

# True  -> excluye internacionales del CSV
# False -> los incluye marcados con is_international=True (default)
EXCLUDE_INTERNATIONAL = True


# =============================================================================
# FUNCIONES
# =============================================================================

def find_section(lines, start_marker, end_marker):
    inside, result = False, []
    for line in lines:
        if start_marker in line:
            inside = True; continue
        if end_marker in line:
            break
        if inside:
            result.append(line.rstrip())
    return result


def parse_bus_line(line):
    line = line.strip()
    if not line or line.startswith('@') or line.startswith('/'):
        return None
    try:
        bus_id   = int(line[:line.index(',')].strip())
        q1       = line.index("'");  q2 = line.index("'", q1+1)
        bus_name = line[q1+1:q2].strip()
        parts    = [p.strip() for p in line[q2+1:].split(',')]
        if parts[0] == '': parts = parts[1:]
        return {
            'bus_id':   bus_id,
            'bus_name': bus_name,
            'baskv_kv': float(parts[0]),
            'ide':      int(parts[1]),
            'area':     int(parts[2]),
            'zone':     int(parts[3]),
            'owner':    int(parts[4]),
            'vm_pu':    float(parts[5]),
            'va_deg':   float(parts[6]),
        }
    except Exception as e:
        print(f"  [WARNING] linea no parseada: {line[:80]} -- {e}")
        return None


IDE_DESC = {1: "PQ", 2: "PV", 3: "slack", 4: "isolated"}


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("01_parse_raw_buses.py -- buses 500 kV desde PSS/E RAW")
    print("=" * 60)

    if not os.path.isfile(RAW_FILE):
        print(f"[ERROR] Archivo no encontrado:\n  {RAW_FILE}"); sys.exit(1)

    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        lines = f.readlines()

    print(f"Caso : {lines[2].rstrip()}")
    print(f"Lineas en archivo: {len(lines)}")

    bus_lines = find_section(lines, "BEGIN BUS DATA", "END OF BUS DATA")
    all_buses = [b for b in (parse_bus_line(l) for l in bus_lines) if b]

    # Filtrar por tension y excluir IDE=4 (desconectados del sistema)
    buses_500 = [b for b in all_buses
                 if KV_MIN <= b['baskv_kv'] <= KV_MAX and b['ide'] != 4]

    print(f"\nTotal buses parseados  : {len(all_buses)}")
    print(f"Buses 500 kV activos   : {len(buses_500)}  (IDE=4 excluidos)")

    # Marcar internacionales por area
    for b in buses_500:
        b['ide_desc'] = IDE_DESC.get(b['ide'], 'unknown')
        country = INTERNATIONAL_AREAS.get(b['area'])
        b['is_international'] = bool(country)
        b['country']          = country or ''

    n_intl = sum(1 for b in buses_500 if b['is_international'])
    print(f"Internacionales (area) : {n_intl}")

    if EXCLUDE_INTERNATIONAL:
        buses_500 = [b for b in buses_500 if not b['is_international']]
        print(f"-> Excluidos. Quedan: {len(buses_500)} buses")
    else:
        print("-> Incluidos con is_international=True  (EXCLUDE_INTERNATIONAL=False)")

    df = pd.DataFrame(buses_500)

    print("\nPor tipo IDE:")
    for ide_val, grp in df.groupby('ide'):
        print(f"  IDE={ide_val} ({IDE_DESC.get(ide_val)}): {len(grp)}")

    intl = df[df['is_international']]
    if not intl.empty:
        print("\nBuses internacionales en rango 500 kV:")
        for _, r in intl.iterrows():
            print(f"  {int(r.bus_id):6}  {r.bus_name:12}  area={int(r.area)}  {r.country}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    col_order = [
        'bus_id', 'bus_name', 'baskv_kv', 'ide', 'ide_desc',
        'area', 'zone', 'owner', 'vm_pu', 'va_deg',
        'is_international', 'country',
    ]
    df[col_order].sort_values('bus_id').reset_index(drop=True).to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} filas)")
    print("Proximo: 02_parse_raw_lines.py")


if __name__ == "__main__":
    main()