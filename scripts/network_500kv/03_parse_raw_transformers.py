"""
03_parse_raw_transformers.py
Extrae transformadores del PSS/E que tienen al menos un devanado en 500 kV.

Fuente  : Official data/PSSE/ver2526pid.raw
Depende : data/network_500kv/buses_500kv_raw.csv  (script 01)
Output  : data/network_500kv/trafos_500kv_raw.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/03_parse_raw_transformers.py

Formato TRANSFORMER DATA en PSS/E v34:
    Transformador de 2 devanados — 4 lineas:
      L1: I,J,0,'CKT',CW,CZ,CM,MAG1,MAG2,NMETR,'NAME',STAT,...
      L2: R1-2, X1-2, SBASE1-2,...
      L3: WINDV1, NOMV1,...  (devanado lado I)
      L4: WINDV2, NOMV2,...  (devanado lado J)

    Transformador de 3 devanados — 5 lineas:
      L1: I,J,K,'CKT',CW,CZ,CM,MAG1,MAG2,NMETR,'NAME',STAT,...
      L2: R1-2, X1-2, SBASE1-2, R2-3, X2-3, SBASE2-3, R3-1, X3-1, SBASE3-1,...
      L3: WINDV1, NOMV1,...  (devanado lado I)
      L4: WINDV2, NOMV2,...  (devanado lado J)
      L5: WINDV3, NOMV3,...  (devanado lado K)

Descomposicion de trafos de 3 devanados:
    PyPSA no tiene componente nativo de trafo de 3 devanados.
    La alternativa clasica es un nodo estrella ficticio, pero eso agrega
    un bus sin sentido fisico por cada trafo 3W (118 buses extra).

    En cambio, descomponemos cada trafo 3W en 2 trafos 2W independientes
    usando siempre el devanado de 500 kV como referencia comun:

        bus_500kV ── trafo_A ── bus_sec1
        bus_500kV ── trafo_B ── bus_sec2

    Parametros electricos asignados segun que bus es el de 500kV:
        Si bus_i es 500kV:
            trafo_A (I-J): R1-2, X1-2, SBASE1-2
            trafo_B (I-K): R3-1, X3-1, SBASE3-1  (invertido K-I -> I-K)
        Si bus_j es 500kV:
            trafo_A (J-I): R1-2, X1-2, SBASE1-2
            trafo_B (J-K): R2-3, X2-3, SBASE2-3
        Si bus_k es 500kV:
            trafo_A (K-I): R3-1, X3-1, SBASE3-1
            trafo_B (K-J): R2-3, X2-3, SBASE2-3

    Esto es fisicamente razonable: cada devanado secundario ve la impedancia
    que lo separa del devanado de alta tension (500 kV).

    El campo 'origin' registra si el trafo viene de un 2W original o de la
    descomposicion de un 3W, para trazabilidad completa hacia el PSS/E.

Campo in_service:
    FORCE_ALL_IN_SERVICE=True  -> todos los trafos quedan in_service=True
                                  representa la red completa en condiciones normales
    FORCE_ALL_IN_SERVICE=False -> in_service refleja el STAT del raw (snapshot puntual)
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

RAW_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
BUSES_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_500kv_raw.csv"
OUTPUT_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "trafos_500kv_raw.csv")

# True  -> todos los trafos quedan in_service=True (red completa, condiciones normales)
# False -> in_service refleja el STAT del raw tal cual (snapshot puntual del PSS/E)
FORCE_ALL_IN_SERVICE = True


# =============================================================================
# FUNCIONES
# =============================================================================

def find_section_lines(all_lines, start_marker, end_marker):
    inside, result = False, []
    for line in all_lines:
        if start_marker in line:
            inside = True; continue
        if inside and end_marker in line:
            break
        if inside:
            result.append(line.rstrip())
    return result


def parse_transformers(trafo_lines, valid_500, id_to_name):
    """
    Parsea el bloque TRANSFORMER DATA del PSS/E.
    Descompone trafos 3W en 2 trafos 2W con bus 500kV como referencia.
    Retorna lista de dicts listos para exportar a CSV.
    """
    rows = []
    i = 0

    while i < len(trafo_lines):
        line = trafo_lines[i].strip()
        if not line or line.startswith('@') or line.startswith('/'):
            i += 1
            continue

        try:
            parts = line.split(',')
            bus_i = int(parts[0].strip())
            bus_j = int(parts[1].strip())
            bus_k = int(parts[2].strip())
            n_wind = 2 if bus_k == 0 else 3

            # Extraer CKT y STAT
            Q = "'"
            p1 = line.index(Q);  p2 = line.index(Q, p1+1)
            p3 = line.index(Q, p2+1); p4 = line.index(Q, p3+1)
            ckt  = line[p1+1:p2].strip()
            rest = [x.strip() for x in line[p4+1:].split(',') if x.strip()]
            stat = int(rest[0])

            # Linea 2: impedancias
            l2 = trafo_lines[i+1].strip() if i+1 < len(trafo_lines) else ''
            l2p = [x.strip() for x in l2.split(',') if x.strip()]

            # Avanzar indice al siguiente trafo
            i += (4 if n_wind == 2 else 5)

            # Filtrar: al menos un lado en 500kV
            buses = {bus_i, bus_j} if n_wind == 2 else {bus_i, bus_j, bus_k}
            if not buses & valid_500:
                continue

            in_service = True if FORCE_ALL_IN_SERVICE else (stat == 1)

            if n_wind == 2:
                # --- Trafo 2 devanados: una sola fila ---
                r12  = float(l2p[0]) if len(l2p) > 0 else np.nan
                x12  = float(l2p[1]) if len(l2p) > 1 else np.nan
                sb12 = float(l2p[2]) if len(l2p) > 2 else np.nan
                ni = id_to_name.get(bus_i, str(bus_i))
                nj = id_to_name.get(bus_j, str(bus_j))
                rows.append({
                    'bus_i':      bus_i,
                    'bus_j':      bus_j,
                    'ckt':        ckt,
                    'r_pu':       r12,
                    'x_pu':       x12,
                    'sbase_mva':  sb12,
                    'in_service': in_service,
                    'origin':     '2W',
                    'trafo_key':  f"{ni}-{nj}-{ckt}",
                })

            else:
                # --- Trafo 3 devanados: descomponer en 2 trafos 2W ---
                # L2: R1-2, X1-2, SBASE1-2, R2-3, X2-3, SBASE2-3, R3-1, X3-1, SBASE3-1
                r12  = float(l2p[0]); x12  = float(l2p[1]); sb12 = float(l2p[2])
                r23  = float(l2p[3]); x23  = float(l2p[4]); sb23 = float(l2p[5])
                r31  = float(l2p[6]); x31  = float(l2p[7]); sb31 = float(l2p[8])

                # Identificar bus de 500kV y asignar impedancias
                if bus_i in valid_500:
                    bus_500, bus_s1, bus_s2 = bus_i, bus_j, bus_k
                    r_a, x_a, sb_a = r12, x12, sb12   # I-J
                    r_b, x_b, sb_b = r31, x31, sb31   # K-I -> usar como I-K
                elif bus_j in valid_500:
                    bus_500, bus_s1, bus_s2 = bus_j, bus_i, bus_k
                    r_a, x_a, sb_a = r12, x12, sb12   # I-J -> usar como J-I
                    r_b, x_b, sb_b = r23, x23, sb23   # J-K
                else:
                    bus_500, bus_s1, bus_s2 = bus_k, bus_i, bus_j
                    r_a, x_a, sb_a = r31, x31, sb31   # K-I
                    r_b, x_b, sb_b = r23, x23, sb23   # J-K -> usar como K-J

                n500 = id_to_name.get(bus_500, str(bus_500))
                ns1  = id_to_name.get(bus_s1,  str(bus_s1))
                ns2  = id_to_name.get(bus_s2,  str(bus_s2))

                rows.append({
                    'bus_i':      bus_500,
                    'bus_j':      bus_s1,
                    'ckt':        ckt,
                    'r_pu':       r_a,
                    'x_pu':       x_a,
                    'sbase_mva':  sb_a,
                    'in_service': in_service,
                    'origin':     '3W_decomp',
                    'trafo_key':  f"{n500}-{ns1}-{ckt}",
                })
                rows.append({
                    'bus_i':      bus_500,
                    'bus_j':      bus_s2,
                    'ckt':        ckt,
                    'r_pu':       r_b,
                    'x_pu':       x_b,
                    'sbase_mva':  sb_b,
                    'in_service': in_service,
                    'origin':     '3W_decomp',
                    'trafo_key':  f"{n500}-{ns2}-{ckt}",
                })

        except Exception as e:
            i += 1

    return rows


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("03_parse_raw_transformers.py -- trafos 500 kV desde PSS/E RAW")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    buses_df   = pd.read_csv(BUSES_FILE)
    valid_500  = set(buses_df['bus_id'].astype(int))
    id_to_name = dict(zip(buses_df['bus_id'].astype(int), buses_df['bus_name']))
    print(f"Buses 500 kV cargados: {len(valid_500)}")

    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        all_lines = f.readlines()

    trafo_lines = find_section_lines(all_lines, "BEGIN TRANSFORMER DATA", "0 / END OF TRANSFORMER DATA")
    print(f"Lineas en TRANSFORMER DATA: {len(trafo_lines)}")

    rows = parse_transformers(trafo_lines, valid_500, id_to_name)
    df = pd.DataFrame(rows)
    df.insert(0, 'trafo_id', range(1, len(df) + 1))

    # Reporte
    orig_2w  = (df['origin'] == '2W').sum()
    orig_3w  = (df['origin'] == '3W_decomp').sum()
    print(f"\nTrafos en output:")
    print(f"  2W originales              : {orig_2w}")
    print(f"  3W descompuestos (x2)      : {orig_3w}  ({orig_3w//2} trafos 3W -> {orig_3w} filas)")
    print(f"  TOTAL filas                : {len(df)}")

    if FORCE_ALL_IN_SERVICE:
        print(f"\n  -> FORCE_ALL_IN_SERVICE=True: todos los trafos marcados in_service=True")
    else:
        in_svc = df['in_service'].sum()
        print(f"\n  -> FORCE_ALL_IN_SERVICE=False")
        print(f"     En servicio    : {in_svc}")
        print(f"     Fuera servicio : {len(df) - in_svc}")

    col_order = [
        'trafo_id', 'trafo_key',
        'bus_i', 'bus_j',
        'ckt', 'origin',
        'r_pu', 'x_pu', 'sbase_mva',
        'in_service',
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df[col_order].to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} filas)")
    print("Proximo: 04_parse_raw_buses_sec.py")


if __name__ == "__main__":
    main()
