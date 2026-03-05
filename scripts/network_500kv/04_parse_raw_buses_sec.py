"""
04_parse_raw_buses_sec.py
Extrae los buses secundarios (lado bajo) de los transformadores 500 kV del PSS/E.

Fuente  : Official data/PSSE/ver2526pid.raw
Depende : data/network_500kv/buses_500kv_raw.csv   (script 01)
          data/network_500kv/trafos_500kv_raw.csv   (script 03)
Output  : data/network_500kv/buses_sec_raw.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/04_parse_raw_buses_sec.py

Logica:
    1. Cargar todos los bus_j unicos del CSV de trafos
    2. Excluir los que ya estan en buses_500kv_raw.csv (valid_500)
       -> Si alguno esta en valid_500 se reporta como alerta (autotrafo)
    3. Para cada bus secundario buscar en el raw: bus_name_psse, baskv_kv, ide
    4. Generar bus_name propio con formato: PARENT_kVkV o PARENT_kVkV_N
       donde PARENT es el nombre del bus 500kV al que conecta
       y N es indice secuencial si hay multiples secundarios del mismo
       nivel de tension para el mismo bus 500kV

Columnas del output:
    bus_id         : ID numerico del bus en PSS/E
    bus_name       : nombre generado (PARENT_kVkV o PARENT_kVkV_N)
    bus_name_psse  : nombre original del raw (trazabilidad hacia PSS/E)
    baskv_kv       : tension base en kV
    ide            : tipo de bus en PSS/E (1=PQ, 2=PV, 3=slack)
    vm_pu          : modulo de tension del caso base PSS/E (pu)
    va_deg         : angulo de tension del caso base PSS/E (grados)
    parent_bus_id  : bus_id del bus 500kV al que conecta via trafo

Notas:
    - Se incluyen TODOS los buses secundarios sin filtro de tension.
      Esto incluye terminales de maquina (11-22 kV) y nodos de red (33-345 kV).
      Decision tomada para reflejar la red completa y permitir conectar
      generacion en el punto exacto que corresponda segun Tavo y Gus.
    - Las coordenadas geograficas se asignan en el script 05, heredando
      las del bus 500kV padre (misma estacion fisica).
"""

import os
import sys
import pandas as pd
from collections import defaultdict

# =============================================================================
# CONFIGURACION
# =============================================================================

RAW_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
BUSES_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_500kv_raw.csv"
TRAFOS_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/trafos_500kv_raw.csv"
OUTPUT_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "buses_sec_raw.csv")


# =============================================================================
# FUNCIONES
# =============================================================================

def parse_all_buses(raw_lines):
    """Parsea la seccion BUS DATA completa del raw. Retorna dict bus_id -> atributos."""
    buses = {}
    inside = False
    for line in raw_lines:
        if "BEGIN BUS DATA" in line:
            inside = True; continue
        if inside and "END OF BUS DATA" in line:
            break
        if inside:
            l = line.strip()
            if not l or l.startswith('@') or l.startswith('/'):
                continue
            try:
                bus_id = int(l[:l.index(',')].strip())
                q1 = l.index("'"); q2 = l.index("'", q1+1)
                bus_name = l[q1+1:q2].strip()
                parts = [p.strip() for p in l[q2+1:].split(',')]
                if parts[0] == '': parts = parts[1:]
                buses[bus_id] = {
                    'bus_name_psse': bus_name,
                    'baskv_kv':      float(parts[0]),
                    'ide':           int(parts[1]),
                }
            except:
                pass
    return buses


IDE_DESC = {1: "PQ", 2: "PV - generador activo", 3: "slack", 4: "isolated - unidad parada en snapshot"}


def build_bus_name(parent_name, kv, index=None):
    """
    Genera nombre de bus secundario.
    Formato: PARENT_kVkV  o  PARENT_kVkV_N si hay multiples del mismo nivel.
    La tension se formatea sin decimales si es entero, con 1 decimal si no.
    """
    kv_str = f"{int(kv)}kV" if kv == int(kv) else f"{kv:.1f}kV"
    base = f"{parent_name}_{kv_str}"
    return base if index is None else f"{base}_{index}"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("04_parse_raw_buses_sec.py -- buses secundarios desde PSS/E RAW")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # Cargar buses 500kV
    buses_500_df = pd.read_csv(BUSES_FILE)
    valid_500    = set(buses_500_df['bus_id'].astype(int))
    id_to_name   = dict(zip(buses_500_df['bus_id'].astype(int), buses_500_df['bus_name']))
    print(f"Buses 500 kV cargados : {len(valid_500)}")

    # Cargar trafos — extraer bus_j unicos y su bus_i (500kV padre)
    trafos_df = pd.read_csv(TRAFOS_FILE)
    print(f"Trafos cargados       : {len(trafos_df)}")

    # Mapear bus_j -> parent bus_i (500kV)
    # Si un bus_j aparece con multiples padres (raro) tomamos el primero
    busj_to_parent = {}
    for _, row in trafos_df.iterrows():
        bj = int(row['bus_j'])
        bi = int(row['bus_i'])
        if bj not in busj_to_parent:
            busj_to_parent[bj] = bi

    # Filtrar: excluir los que ya estan en valid_500
    autotrafos = {bj for bj in busj_to_parent if bj in valid_500}
    if autotrafos:
        print(f"\n  ⚠ ALERTA: {len(autotrafos)} bus_j estan en valid_500 (autotrafos):")
        for b in sorted(autotrafos):
            print(f"    bus_id={b}  {id_to_name.get(b,'?')}")

    secondary_ids = {bj for bj in busj_to_parent if bj not in valid_500}
    print(f"\nBuses secundarios unicos: {len(secondary_ids)}")

    # Parsear todos los buses del raw
    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        raw_lines = f.readlines()
    all_buses = parse_all_buses(raw_lines)

    # Verificar que todos los secundarios esten en el raw
    not_found = secondary_ids - set(all_buses.keys())
    if not_found:
        print(f"  ⚠ {len(not_found)} buses secundarios no encontrados en el raw:")
        for b in sorted(not_found):
            print(f"    {b}")

    # Construir nombres: agrupar por (parent, kv) para detectar multiples
    # parent_kv -> lista de bus_ids
    parent_kv_groups = defaultdict(list)
    for bid in sorted(secondary_ids):
        if bid not in all_buses:
            continue
        parent_id = busj_to_parent[bid]
        parent_name = id_to_name.get(parent_id, str(parent_id))
        kv = all_buses[bid]['baskv_kv']
        parent_kv_groups[(parent_name, kv)].append(bid)

    # Asignar nombres
    bus_name_map = {}  # bus_id -> bus_name generado
    multiples = {}     # (parent, kv) -> lista si hay mas de 1

    for (parent_name, kv), bid_list in parent_kv_groups.items():
        if len(bid_list) == 1:
            bus_name_map[bid_list[0]] = build_bus_name(parent_name, kv)
        else:
            multiples[(parent_name, kv)] = bid_list
            for idx, bid in enumerate(sorted(bid_list), start=1):
                bus_name_map[bid] = build_bus_name(parent_name, kv, idx)

    # Construir output
    rows = []
    for bid in sorted(secondary_ids):
        if bid not in all_buses:
            continue
        parent_id = busj_to_parent[bid]
        raw_info  = all_buses[bid]
        rows.append({
            'bus_id':        bid,
            'bus_name':      bus_name_map.get(bid, f"BUS_{bid}"),
            'bus_name_psse': raw_info['bus_name_psse'],
            'baskv_kv':      raw_info['baskv_kv'],
            'ide':           raw_info['ide'],
            'ide_desc':      IDE_DESC.get(raw_info['ide'], 'unknown'),
            'vm_pu':         raw_info.get('vm_pu'),
            'va_deg':        raw_info.get('va_deg'),
            'parent_bus_id': parent_id,
        })

    df = pd.DataFrame(rows)

    # Reporte de multiples
    if multiples:
        print(f"\nBuses secundarios con multiples nodos por tension:")
        for (parent, kv), bid_list in sorted(multiples.items()):
            kv_str = f"{int(kv)}kV" if kv == int(kv) else f"{kv:.1f}kV"
            names = [bus_name_map[b] for b in sorted(bid_list)]
            print(f"  {parent:<20} {kv_str:<8}: {len(bid_list)} buses -> {names}")

    # Distribucion por tension
    print(f"\nDistribucion por tension:")
    for kv, grp in df.groupby('baskv_kv'):
        kv_str = f"{int(kv)}kV" if kv == int(kv) else f"{kv:.1f}kV"
        print(f"  {kv_str:<10}: {len(grp)} buses")

    # Reporte por IDE
    print(f"\nDistribucion por IDE (util para Tavo al conectar generacion):")
    ide_map = {1: "PQ (barra de red)", 2: "PV (generador activo)", 3: "slack", 4: "isolated (unidad parada en snapshot)"}
    for ide_val, grp in df.groupby('ide'):
        print(f"  IDE={ide_val} {ide_map.get(ide_val,'?'):<35}: {len(grp)} buses")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} filas)")
    print("Proximo: 05_match_geosadi_coords.py")


if __name__ == "__main__":
    main()
