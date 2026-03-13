"""
11_add_geo_to_generators.py
Asigna coordenadas geograficas y nombre GeoSADI a cada generador de
generators_mapped.csv.

Inputs:
    data/network_500kv/generators_mapped.csv
    data/network_500kv/buses_final.csv
    Official data/GEOSADI/CSV/centrales_electricas.csv

Outputs:
    data/network_500kv/generators_readypypsa.csv
        Una fila por generador. Tienen nombre_geosadi Y bus_conexion500kv
        resueltos. Son los candidatos directos a entrar a PyPSA.
        El script 12 los une con las filas resueltas del pending para
        formar generators_final.csv.

    data/network_500kv/generators_pendingmanualpypsa.csv
        Agrupa generadores a los que les falta nombre_geosadi,
        bus_conexion500kv, o ambos.
        Columna 'falta': 'geo' / 'bus' / 'ambos'
        Columna 'comentario': vacia, completar manualmente con la
            decision tomada (ej: 'red interna ALUAR, no va a PyPSA').

        Para resolver entradas del pending:
            - Si se completa nombre_geosadi: poner geo_match = 'manual'
            - Si se completa bus_conexion500kv_manual: poner match_type = 'manual'
            - Si la central no va a PyPSA: completar solo comentario

        Una vez completado, el script 12 hace join de readypypsa +
        filas del pending con ambos campos completos -> generators_final.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/11_add_geo_to_generators.py

============================================================
MATCHING GEOGRAFICO
============================================================

Se comparan los primeros 4 caracteres del bus_name_origen (PSS/E) contra
los primeros 4 caracteres del campo Nemo de centrales_electricas.csv.

Un unico candidato, o multiples resueltos por tipo -> geo_match='exacto'.
Multiples candidatos no resolubles por tipo -> geo_match='a_revisar'.
Sin candidatos -> geo_match='sin_match'.

Para casos con ambiguedad, se usa el diccionario NEMO_PREFERIDO que
asigna explicitamente bus_name_origen -> Nemo GeoSADI.

INDICE CARRIER -> TIPO GEOSADI:
    ocgt         -> TG        steam        -> TV
    hydro        -> HI, HR    diesel       -> DI
    ccgt         -> CC        nuclear      -> NU
    wind         -> EO        solar        -> FV
    biogas       -> BG        biomass      -> BM
    battery      -> BESS      pumped_hydro -> HB

============================================================
OVERRIDES DE CARRIER
============================================================

Tipo GeoSADI HB -> carrier = 'pumped_hydro'
    Unico caso en Argentina: Rio Grande (750 MW).

Tipo GeoSADI VG -> se acepta si carrier PSS/E en {ocgt, steam, ccgt}.
    De lo contrario se marca 'VG_revisar' y va al pending.

============================================================
CRITERIO DE SEPARACION
============================================================

generators_readypypsa (individual):
    geo_match == 'exacto'  AND  bus_conexion500kv no vacio

generators_pendingmanualpypsa.csv (una fila por generador):
    Todo lo demas. Columnas a completar manualmente:
            Para resolver entradas del pending completar las columnas:
            nombre_geosadi          -> si falta geo, poner geo_match='manual'
            bus_conexion500kv_manual -> si falta bus, poner match_type='manual'
            comentario              -> siempre (ej: 'red interna ALUAR, no va a PyPSA')
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

GENERATORS_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_mapped.csv"
CENTRALES_FILE   = "/mnt/c/Work/pypsa-ar-sandbox/Official data/GEOSADI/CSV/centrales_electricas.csv"
BUSES_FILE       = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_final.csv"
OUTPUT_DIR       = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_READY     = os.path.join(OUTPUT_DIR, "generators_readypypsa.csv")
OUTPUT_PENDING   = os.path.join(OUTPUT_DIR, "generators_pendingmanualpypsa.csv")

CARRIER_TO_TIPO = {
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

VG_CARRIERS_VALIDOS = {'ocgt', 'steam', 'ccgt'}

TIPO_OVERRIDE = {
    'HB': 'pumped_hydro',
}

NEMO_PREFERIDO = {
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
# MATCHING GEOGRAFICO
# =============================================================================

def build_nemo_index(centrales):
    centrales = centrales.copy()
    centrales['nemo4'] = centrales['Nemo'].str[:4].str.upper()
    nemo4_index     = {}
    nemo_full_index = {}
    for _, row in centrales.iterrows():
        nemo4_index.setdefault(row['nemo4'], []).append(row)
        nemo_full_index[str(row['Nemo']).strip().upper()] = row
    return nemo4_index, nemo_full_index


def resolve_match(bus_name_origen, carrier, nemo4_index, nemo_full_index):
    bus_name_clean = bus_name_origen.strip().upper()

    if bus_name_clean in NEMO_PREFERIDO:
        nemo_key = NEMO_PREFERIDO[bus_name_clean].upper()
        if nemo_key in nemo_full_index:
            return nemo_full_index[nemo_key], 'exacto'

    prefix4    = bus_name_clean[:4]
    candidates = nemo4_index.get(prefix4, [])

    if not candidates:
        return None, 'sin_match'
    if len(candidates) == 1:
        return candidates[0], 'exacto'

    tipos_validos = CARRIER_TO_TIPO.get(carrier, [])
    filtered = [r for r in candidates if r['Tipo'] in tipos_validos]
    if len(filtered) == 1:
        return filtered[0], 'exacto'

    return None, 'a_revisar'


def tiene_bus(bus_con):
    if bus_con is None:
        return False
    s = str(bus_con).strip()
    return s != '' and s.lower() != 'nan'


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("11_add_geo_to_generators.py -- coordenadas GeoSADI")
    print("=" * 60)

    for f in [GENERATORS_FILE, CENTRALES_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    gens      = pd.read_csv(GENERATORS_FILE)
    centrales = pd.read_csv(CENTRALES_FILE)
    buses_df  = pd.read_csv(BUSES_FILE)

    print(f"Generadores cargados          : {len(gens)}")
    print(f"Centrales GeoSADI             : {len(centrales)}")
    print(f"Buses del modelo              : {len(buses_df)}")

    nemo4_index, nemo_full_index = build_nemo_index(centrales)

    print(f"\nEjecutando matching geografico + resolucion manual...")

    nombres_geosadi  = []
    lats             = []
    lons             = []
    geo_matches      = []
    carriers_out     = []
    match_types_out  = []
    bus_con_out      = []
    bus_con_name_out = []

    n_exacto = n_sin_match = n_a_revisar = 0
    n_override_hb = n_vg_revisar = 0
    warnings = []

    for _, row in gens.iterrows():
        bus_name   = str(row['bus_name_origen'])
        carrier    = str(row['carrier'])
        match_type = str(row['match_type'])
        bus_con    = row['bus_conexion500kv']
        bus_con_nm = row['bus_conexion500kv_name']

        geo_row, status = resolve_match(bus_name, carrier, nemo4_index, nemo_full_index)

        if geo_row is None:
            nombre = ''
            lat    = np.nan
            lon    = np.nan
            if status == 'sin_match':
                n_sin_match += 1
            else:
                n_a_revisar += 1
                candidatos = nemo4_index.get(bus_name.strip().upper()[:4], [])
                warnings.append(
                    f"  a_revisar: {row['gen_key']}  bus={bus_name.strip()}"
                    f"  carrier={carrier}  candidatos={[r['Nemo'] for r in candidatos]}"
                )
        else:
            nombre = geo_row['Nombre']
            lat    = geo_row['latitude']
            lon    = geo_row['longitude']
            tipo   = geo_row['Tipo']
            n_exacto += 1
            if tipo in TIPO_OVERRIDE:
                carrier = TIPO_OVERRIDE[tipo]
                n_override_hb += 1
            elif tipo == 'VG':
                if carrier not in VG_CARRIERS_VALIDOS:
                    warnings.append(
                        f"  VG_revisar: {row['gen_key']}  bus={bus_name.strip()}"
                        f"  carrier_psse={carrier}  central={nombre}"
                    )
                    carrier = 'VG_revisar'
                    n_vg_revisar += 1

        nombres_geosadi.append(nombre)
        lats.append(lat)
        lons.append(lon)
        geo_matches.append(status)
        carriers_out.append(carrier)
        match_types_out.append(match_type)
        bus_con_out.append(bus_con)
        bus_con_name_out.append(bus_con_nm)

    df_out = gens.copy()
    df_out['carrier']                = carriers_out
    df_out['nombre_geosadi']         = nombres_geosadi
    df_out['lat']                    = lats
    df_out['lon']                    = lons
    df_out['geo_match']              = geo_matches
    df_out['match_type']             = match_types_out
    df_out['bus_conexion500kv']      = bus_con_out
    df_out['bus_conexion500kv_name'] = bus_con_name_out

    COLS = [
        'gen_key', 'bus_id_origen', 'bus_name_origen', 'nombre_geosadi', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'lat', 'lon',
        'geo_match', 'match_type',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_saltos', 'camino',
    ]
    df_out = df_out[COLS]

    # ==========================================================
    # SEPARACION ready vs pending
    # ==========================================================
    mask_geo = df_out['geo_match'] == 'exacto'
    mask_bus = df_out['bus_conexion500kv'].apply(tiene_bus)
    mask_carrier = df_out['carrier'] != 'VG_revisar'

    df_ready       = df_out[mask_geo & mask_bus & mask_carrier].copy()
    df_pending_ind = df_out[~(mask_geo & mask_bus & mask_carrier)].copy()

    def get_falta(row):
        tiene_g = row['geo_match'] == 'exacto'
        tiene_b = tiene_bus(row['bus_conexion500kv'])
        if not tiene_g and not tiene_b: return 'ambos'
        if not tiene_g: return 'geo'
        return 'bus'
    df_pending_ind['falta'] = df_pending_ind.apply(get_falta, axis=1)

    df_pending = df_pending_ind[[
        'gen_key', 'bus_id_origen', 'bus_name_origen', 'nombre_geosadi', 'falta', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'lat', 'lon',
        'geo_match', 'match_type',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_saltos', 'camino',
    ]].copy()
    df_pending['COMENTARIOS'] = ''
    df_pending = df_pending.sort_values('pt_mw', ascending=False)

    # ==========================================================
    # REPORTE
    # ==========================================================
    total = len(df_out)
    print(f"\n{'='*60}")
    print(f"MATCHING GEOGRAFICO")
    print(f"{'='*60}")
    print(f"  exacto     : {n_exacto:>4}  ({n_exacto/total*100:.1f}%)")
    print(f"  sin_match  : {n_sin_match:>4}  ({n_sin_match/total*100:.1f}%)")
    print(f"  a_revisar  : {n_a_revisar:>4}  ({n_a_revisar/total*100:.1f}%)")

    print(f"\n{'='*60}")
    print(f"OVERRIDES DE CARRIER")
    print(f"{'='*60}")
    print(f"  HB -> pumped_hydro : {n_override_hb} generadores")
    print(f"  VG_revisar         : {n_vg_revisar} generadores")

    if warnings:
        print(f"\n  Warnings ({len(warnings)}):")
        for w in warnings:
            print(w)

    print(f"\n{'='*60}")
    print(f"SEPARACION OUTPUTS")
    print(f"{'='*60}")
    mw_ready   = df_ready[df_ready['pt_mw'] < 9000]['pt_mw'].sum()
    mw_pending = df_pending[df_pending['pt_mw'] < 9000]['pt_mw'].sum()
    print(f"  generators_readypypsa        : {len(df_ready):>4} generadores  {mw_ready:>10,.1f} MW")
    print(f"  generators_pendingmanualpypsa: {len(df_pending):>4} generadores  {mw_pending:>10,.1f} MW")

    print(f"\n  Pending agrupado por carrier:")
    for carrier, grp in df_pending.groupby('carrier'):
        mw = grp[grp['pt_mw'] < 9000]['pt_mw'].sum()
        print(f"    {carrier:<15}: {len(grp):>4} gen   {mw:>10,.1f} MW")

    print(f"\n{'='*60}")
    print(f"DISTRIBUCION POR CARRIER (readypypsa, STAT=1, pt < 9999)")
    print(f"{'='*60}")
    activos = df_ready[(df_ready['stat'] == 1) & (df_ready['pt_mw'] < 9990)]
    for carrier, grp in activos.groupby('carrier'):
        print(f"  {carrier:<15}: {len(grp):>4} gen   {grp['pt_mw'].sum():>10,.1f} MW")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_ready.to_csv(OUTPUT_READY, index=False)
    df_pending.to_csv(OUTPUT_PENDING, index=False)
    print(f"\n✔ {OUTPUT_READY}    ({len(df_ready)} filas)")
    print(f"✔ {OUTPUT_PENDING}  ({len(df_pending)} filas)")
    print(f"\nProximo: 12_build_generators_final.py")


if __name__ == "__main__":
    main()
