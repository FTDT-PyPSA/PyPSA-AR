"""
11_add_geo_to_generators.py
Asigna coordenadas geograficas y nombre GeoSADI a cada generador de
generators_mapped.csv. Resuelve ademas bus_conexion500kv para los
generadores sin_conexion usando la asignacion manual completada.
Aplica overrides de carrier para tipos especiales (HB, VG).

Inputs:
    data/network_500kv/generators_mapped.csv
    data/network_500kv/generators_manual_assignment_completed.csv
    data/network_500kv/buses_final.csv
    Official data/GEOSADI/CSV/centrales_electricas.csv

Outputs:
    data/network_500kv/generators_final.csv
        Generadores con coordenadas GeoSADI resueltas (geo_match='exacto').
        Incluye generadores con bus_conexion500kv vacio -- la conexion
        a la red puede forzarse manualmente en etapas posteriores.

    data/network_500kv/generators_pending.csv
        Generadores sin coordenadas GeoSADI (geo_match='sin_match' o
        'a_revisar'). Requieren revision manual para completar nombre
        y coordenadas de la central.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/11_add_geo_to_generators.py

============================================================
MATCHING GEOGRAFICO
============================================================

Se comparan los primeros 4 caracteres del bus_name_origen contra los
primeros 4 caracteres del campo Nemo de centrales_electricas.csv.

Un unico candidato, o multiples resueltos por carrier -> geo_match='exacto'.
Multiples candidatos no resueltos por carrier -> geo_match='a_revisar',
    coordenadas vacias, warning en reporte.
Sin candidatos -> geo_match='sin_match'.

INDICE CARRIER -> TIPO GEOSADI:
    ocgt         -> TG        steam        -> TV
    hydro        -> HI, HR    diesel       -> DI
    ccgt         -> CC        nuclear      -> NU
    wind         -> EO        solar        -> FV
    biogas       -> BG        biomass      -> BM
    battery      -> BESS      pumped_hydro -> HB

============================================================
OVERRIDE DE CARRIERS
============================================================

Tipo GeoSADI HB -> carrier = 'pumped_hydro'
    Unico caso en Argentina: Rio Grande (750 MW).

Tipo GeoSADI VG -> se acepta si carrier es ocgt, steam o ccgt.
    De lo contrario se marca 'VG_revisar'.

============================================================
CASOS ESPECIALES (NEMO_PREFERIDO)
============================================================

Diccionario de asignacion explicita bus_name_origen -> Nemo GeoSADI
para casos donde el matching automatico no puede resolver por carrier.

Salto Grande tiene representacion argentina (SGDEHIAR) y uruguaya
(SGDEHIUR). Los buses argentinos y uruguayos se asignan explicitamente.

============================================================
RESOLUCION MANUAL DE bus_conexion500kv
============================================================

Para generadores con match_type='sin_conexion' se hace join contra
generators_manual_assignment_completed.csv por central_prefix
(primeros 6 caracteres del bus_name_origen).

Si bus_conexion500kv_manual tiene valor: match_type se actualiza a
'manual' y bus_conexion500kv queda resuelto.
Si esta vacio: match_type permanece 'sin_conexion'.

============================================================
COLUMNAS DE LOS OUTPUTS
============================================================

    gen_key               : clave unica PSS/E (bus_id_origen-gen_id)
    bus_id_origen         : bus_id PSS/E donde conecta el generador
    bus_name_origen       : nombre del bus origen en PSS/E
    nombre_geosadi        : nombre de la central en GeoSADI
    carrier               : tipo tecnologico
    pg_mw                 : despacho activo en snapshot (MW)
    pt_mw                 : potencia maxima PSS/E (MW)
    stat                  : estado en snapshot (1=en servicio, 0=fuera)
    lat                   : latitud de la central GeoSADI
    lon                   : longitud de la central GeoSADI
    geo_match             : 'exacto' / 'sin_match' / 'a_revisar'
    match_type            : 'directo' / 'bfs' / 'manual' / 'sin_conexion'
    bus_conexion500kv     : bus_id del nodo del modelo asignado
    bus_conexion500kv_name: nombre del nodo en el modelo 500 kV
    n_saltos              : saltos BFS hasta destino
    camino                : ruta BFS desde origen hasta destino
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
COMPLETED_FILE   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_manual_assignment_completed.csv"
BUSES_FILE       = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_final.csv"
OUTPUT_DIR       = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FINAL     = os.path.join(OUTPUT_DIR, "generators_final.csv")
OUTPUT_PENDING   = os.path.join(OUTPUT_DIR, "generators_pending.csv")

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

# Asignacion explicita bus_name_origen -> Nemo GeoSADI
# para casos donde el matching automatico no puede resolver.
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
    """Construye indice nemo4 -> lista de filas, y nemo_completo -> fila."""
    centrales = centrales.copy()
    centrales['nemo4'] = centrales['Nemo'].str[:4].str.upper()
    nemo4_index     = {}
    nemo_full_index = {}
    for _, row in centrales.iterrows():
        nemo4_index.setdefault(row['nemo4'], []).append(row)
        nemo_full_index[str(row['Nemo']).strip().upper()] = row
    return nemo4_index, nemo_full_index


def resolve_match(bus_name_origen, carrier, nemo4_index, nemo_full_index):
    """
    Busca la central GeoSADI correspondiente a un generador.
    Retorna (row_geosadi, geo_match) o (None, geo_match).

    Prioridad:
        1. Lookup explicito en NEMO_PREFERIDO por bus_name_origen
        2. Match por nemo4 + desambiguacion por carrier
    """
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


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("11_add_geo_to_generators.py -- coordenadas GeoSADI")
    print("=" * 60)

    for f in [GENERATORS_FILE, CENTRALES_FILE, COMPLETED_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    gens      = pd.read_csv(GENERATORS_FILE)
    centrales = pd.read_csv(CENTRALES_FILE)
    completed = pd.read_csv(COMPLETED_FILE)
    buses_df  = pd.read_csv(BUSES_FILE)

    print(f"Generadores cargados          : {len(gens)}")
    print(f"Centrales GeoSADI             : {len(centrales)}")
    print(f"Entradas asignacion manual    : {len(completed)}")
    print(f"Buses del modelo              : {len(buses_df)}")

    name_to_id = dict(zip(buses_df['bus_name'], buses_df['bus_id']))

    # Normalizar columna del completed (acepta nombre viejo y nuevo)
    if 'bus_destino_manual' in completed.columns and 'bus_conexion500kv_manual' not in completed.columns:
        completed = completed.rename(columns={'bus_destino_manual': 'bus_conexion500kv_manual'})

    completed_valido = completed[
        completed['bus_conexion500kv_manual'].notna() &
        (completed['bus_conexion500kv_manual'].astype(str).str.strip() != '')
    ].copy()

    completed_index = dict(zip(
        completed_valido['central_prefix'].str.strip().str.upper(),
        completed_valido['bus_conexion500kv_manual'].astype(str).str.strip()
    ))

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

    n_exacto          = 0
    n_sin_match       = 0
    n_a_revisar       = 0
    n_override_hb     = 0
    n_vg_revisar      = 0
    n_manual_resuelto = 0
    warnings          = []

    for _, row in gens.iterrows():
        bus_name   = str(row['bus_name_origen'])
        prefix6    = bus_name[:6].upper()
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

        # Resolucion manual para sin_conexion
        if match_type == 'sin_conexion' and prefix6 in completed_index:
            bus_name_manual = completed_index[prefix6]
            bus_id_manual   = name_to_id.get(bus_name_manual)
            if bus_id_manual is not None:
                bus_con    = bus_id_manual
                bus_con_nm = bus_name_manual
                match_type = 'manual'
                n_manual_resuelto += 1
            else:
                warnings.append(
                    f"  Bus manual no encontrado en buses_final: '{bus_name_manual}'"
                    f"  (central_prefix={prefix6})"
                )

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

    df_out = df_out[[
        'gen_key', 'bus_id_origen', 'bus_name_origen', 'nombre_geosadi', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'lat', 'lon',
        'geo_match', 'match_type',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_saltos', 'camino',
    ]]

    df_final   = df_out[df_out['geo_match'] == 'exacto'].copy()
    df_pending = df_out[df_out['geo_match'] != 'exacto'].copy()

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

    mw_final   = df_final[df_final['pt_mw'] < 9000]['pt_mw'].sum()
    mw_pending = df_pending[df_pending['pt_mw'] < 9000]['pt_mw'].sum()
    print(f"\n  MW generators_final   : {mw_final:>10,.1f} MW  ({mw_final/(mw_final+mw_pending)*100:.1f}%)")
    print(f"  MW generators_pending : {mw_pending:>10,.1f} MW  ({mw_pending/(mw_final+mw_pending)*100:.1f}%)")

    print(f"\n{'='*60}")
    print(f"MATCH_TYPE EN generators_final")
    print(f"{'='*60}")
    for mt, grp in df_final.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9000]['pt_mw'].sum()
        print(f"  {mt:<15}: {len(grp):>4} gen   {mw:>10,.1f} MW")

    print(f"\n{'='*60}")
    print(f"RESOLUCION MANUAL")
    print(f"{'='*60}")
    print(f"  Resueltos via completed : {n_manual_resuelto}")
    sin_con_restantes = len(df_out[df_out['match_type'] == 'sin_conexion'])
    print(f"  sin_conexion restantes  : {sin_con_restantes}")

    print(f"\n{'='*60}")
    print(f"PURIFICACION DE CARRIERS")
    print(f"{'='*60}")
    print(f"  HB -> pumped_hydro : {n_override_hb} generadores")
    print(f"  VG_revisar         : {n_vg_revisar} generadores")

    if warnings:
        print(f"\n  Warnings ({len(warnings)}):")
        for w in warnings:
            print(w)
    else:
        print(f"\n  Sin warnings.")

    print(f"\n{'='*60}")
    print(f"DISTRIBUCION FINAL POR CARRIER (STAT=1, pt < 9999)")
    print(f"{'='*60}")
    activos = df_final[(df_final['stat'] == 1) & (df_final['pt_mw'] < 9990)]
    for carrier, grp in activos.groupby('carrier'):
        print(f"  {carrier:<15}: {len(grp):>4} gen   {grp['pt_mw'].sum():>10,.1f} MW")

    print(f"\n{'='*60}")
    print(f"GENERATORS_PENDING (sin coordenadas GeoSADI)")
    print(f"{'='*60}")
    if len(df_pending) > 0:
        df_pending_show = df_pending.copy()
        df_pending_show['prefix4'] = df_pending_show['bus_name_origen'].str[:4]
        resumen_p = (
            df_pending_show.groupby(['prefix4', 'carrier', 'geo_match'])
            .agg(n_gen=('gen_key', 'count'), pt_mw=('pt_mw', 'sum'))
            .sort_values('pt_mw', ascending=False)
        )
        print(resumen_p.to_string())
    else:
        print("  Sin generadores pendientes.")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FINAL, index=False)
    df_pending.to_csv(OUTPUT_PENDING, index=False)
    print(f"\n✔ {OUTPUT_FINAL}    ({len(df_final)} filas)")
    print(f"✔ {OUTPUT_PENDING}  ({len(df_pending)} filas)")
    print(f"\nProximo: 12_add_to_pypsa.py")


if __name__ == "__main__":
    main()
