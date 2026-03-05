"""
02_parse_raw_lines.py
Extrae lineas 500 kV del .raw del PSSE y exporta a CSV.

Fuente  : Official data/PSSE/ver2526pid.raw
Depende : data/network_500kv/buses_500kv_raw.csv (output script 01)
Output  : data/network_500kv/lines_500kv_raw.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/02_parse_raw_lines.py

Formato BRANCH DATA en PSS/E v34:
    I,J,'CKT',R,X,B,'NAME',RATEA..RATEK,GI,BI,GJ,BJ,ST,MET,LEN,...

Campos extraidos:
    I, J       : buses extremos
    CKT        : ID de circuito -- identifica lineas paralelas entre mismos buses
    R, X, B    : resistencia, reactancia, susceptancia [pu, Sbase=100 MVA]
    RATEA      : capacidad termica [MVA] (Rating Set 1 en PSS/E)
    ST         : estado (1=en servicio, 0=fuera de servicio)
    LEN        : longitud [km]

Campos descartados:
    RATEB..K        : ratings alternativos -- iguales a RATEA en este modelo
    GI,BI,GJ,BJ     : admitancias shunt en extremos -- despreciables en transporte
    MET             : referencia de medicion de perdidas -- no relevante para PyPSA
    O1,F1...        : propietario y fraccion

Filtro de internacionales:
    valid_ids viene del CSV del script 01. Si ese CSV excluye internacionales
    (EXCLUDE_INTERNATIONAL=True), las ramas con esos buses quedan fuera automaticamente.

Criterios de clasificacion:
    element_type=series_compensator : X<0 (compensador serie capacitivo)
    element_type=line               : resto
    rating_defined=False            : RATEA=0 en el .raw (sin limite termico definido)
                                      ratea_mva se setea a NaN en esos casos

Campo in_service:
    FORCE_ALL_IN_SERVICE=True  -> todas las ramas quedan in_service=True
                                  representa la red completa en condiciones normales
    FORCE_ALL_IN_SERVICE=False -> in_service refleja el ST del raw (snapshot puntual)
"""

import os, sys
import numpy as np
import pandas as pd
from collections import Counter

# =============================================================================
# CONFIGURACION
# =============================================================================

RAW_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
BUSES_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_500kv_raw.csv"
OUTPUT_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "lines_500kv_raw.csv")

# True  -> incluye lineas ST=0 en el CSV
# False -> solo lineas en servicio
INCLUDE_OUT_OF_SERVICE = True

# True  -> fuerza in_service=True en todas las ramas (red completa, condiciones normales)
# False -> in_service refleja el ST del raw tal cual (snapshot puntual del PSS/E)
FORCE_ALL_IN_SERVICE = True


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


def parse_branch_line(line):
    """
    Formato: I,J,'CKT',R,X,B,'NAME',RATEA..RATEK,GI,BI,GJ,BJ,ST,MET,LEN,...
    Dos strings entre comillas: CKT y nombre de linea (ignorado).
    Layout tras el nombre (12 rating sets):
      rest[0..11]=RATEA..RATEK  rest[12..15]=GI,BI,GJ,BJ  rest[16]=ST  rest[17]=MET  rest[18]=LEN
    """
    line = line.strip()
    if not line or line.startswith('@') or line.startswith('/'):
        return None
    Q = "'"
    try:
        p1 = line.index(Q);  p2 = line.index(Q, p1+1)
        p3 = line.index(Q, p2+1); p4 = line.index(Q, p3+1)
        ij   = [x.strip() for x in line[:p1].split(',') if x.strip()]
        rxb  = [x.strip() for x in line[p2+1:p3].split(',') if x.strip()]
        rest = [x.strip() for x in line[p4+1:].split(',') if x.strip()]
        return {
            'bus_i':     ij[0],
            'bus_j':     ij[1],
            'ckt':       line[p1+1:p2].strip(),
            'r_pu':      float(rxb[0]),
            'x_pu':      float(rxb[1]),
            'b_pu':      float(rxb[2]),
            'ratea_mva': float(rest[0]),
            'st':        int(rest[16]),
            'len_km':    float(rest[18]),
        }
    except Exception as e:
        print(f"  [WARNING] linea no parseada: {line[:80]} -- {e}")
        return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("02_parse_raw_lines.py -- lineas 500 kV desde PSS/E RAW")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}"); sys.exit(1)

    # valid_ids y mapa id->nombre vienen del script 01
    buses_df   = pd.read_csv(BUSES_FILE)
    valid_ids  = set(buses_df['bus_id'].astype(str))
    id_to_name = dict(zip(buses_df['bus_id'].astype(str), buses_df['bus_name']))
    print(f"Buses validos cargados desde script 01 : {len(valid_ids)}")

    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        lines = f.readlines()
    print(f"Caso : {lines[2].rstrip()}")

    branch_lines = find_section(lines, "BEGIN BRANCH DATA", "END OF BRANCH DATA")
    all_branches = [b for b in (parse_branch_line(l) for l in branch_lines) if b]
    print(f"\nTotal ramas en el modelo        : {len(all_branches)}")

    # Ambos extremos deben estar en valid_ids
    branches_500 = [b for b in all_branches
                    if b['bus_i'] in valid_ids and b['bus_j'] in valid_ids]
    print(f"Ramas 500 kV (ambos extremos)   : {len(branches_500)}")

    in_svc  = sum(1 for b in branches_500 if b['st'] == 1)
    out_svc = sum(1 for b in branches_500 if b['st'] == 0)
    print(f"  En servicio    (ST=1) : {in_svc}")
    print(f"  Fuera servicio (ST=0) : {out_svc}")

    if not INCLUDE_OUT_OF_SERVICE:
        branches_500 = [b for b in branches_500 if b['st'] == 1]
        print(f"  -> ST=0 excluidas (INCLUDE_OUT_OF_SERVICE=False). Quedan: {len(branches_500)}")
    else:
        print(f"  -> ST=0 incluidas (INCLUDE_OUT_OF_SERVICE=True)")

    # Asignar in_service
    if FORCE_ALL_IN_SERVICE:
        for b in branches_500:
            b['in_service'] = True
        print(f"  -> FORCE_ALL_IN_SERVICE=True: todas las ramas marcadas in_service=True")
    else:
        for b in branches_500:
            b['in_service'] = (b['st'] == 1)
        print(f"  -> FORCE_ALL_IN_SERVICE=False: in_service refleja ST del raw")

    for b in branches_500:
        name_i = id_to_name.get(b['bus_i'], b['bus_i'])
        name_j = id_to_name.get(b['bus_j'], b['bus_j'])
        ckt_map = {'A': '1', 'B': '2', 'C': '3', 'D': '4', 'E': '5'}
        b['ckt'] = ckt_map.get(b['ckt'].upper(), b['ckt'])
        b['line_key']       = f"{name_i}-{name_j}-{b['ckt']}"
        b['element_type']   = 'series_compensator' if (b['x_pu'] < 0) else 'line'
        b['rating_defined'] = (b['ratea_mva'] != 0)
        if not b['rating_defined']:
            b['ratea_mva'] = np.nan

    df = pd.DataFrame(branches_500)

    print("\nPor tipo de elemento:")
    for etype, grp in df.groupby('element_type'):
        print(f"  {etype}: {len(grp)}")

    n_no_rating = (~df['rating_defined']).sum()
    if n_no_rating:
        print(f"\nLineas sin rating definido (ratea_mva=NaN): {n_no_rating}")
        for _, r in df[~df['rating_defined']].iterrows():
            print(f"  {r.line_key}")

    pair_counts = Counter(f"{r.bus_i}-{r.bus_j}" for _, r in df.iterrows())
    parallel = sorted([(k,v) for k,v in pair_counts.items() if v > 1], key=lambda x: -x[1])
    print(f"\nPares con circuitos paralelos: {len(parallel)}")
    for k, v in parallel:
        print(f"  {k}: {v} circuitos")

    df = df.sort_values(['bus_i', 'bus_j', 'ckt']).reset_index(drop=True)
    df.insert(0, 'line_id', range(1, len(df) + 1))

    col_order = [
        'line_id', 'line_key',
        'bus_i', 'bus_j', 'ckt',
        'r_pu', 'x_pu', 'b_pu',
        'ratea_mva', 'rating_defined',
        'len_km', 'element_type',
        'in_service',
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df[col_order].to_csv(OUTPUT_FILE, index=False)

    print(f"\nâ {OUTPUT_FILE}  ({len(df)} filas)")
    print("Proximo: 03_parse_raw_transformers.py")


if __name__ == "__main__":
    main()