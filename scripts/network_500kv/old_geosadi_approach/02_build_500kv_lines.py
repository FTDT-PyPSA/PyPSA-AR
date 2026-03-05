"""
Script 02 — build_500kv_lines.py
Proyecto: PyPSA-AR
Descripcion: Construye lines_500kv.csv y actualiza buses_500kv.csv con buses nuevos
             detectados automaticamente desde la geometria.

Inputs:
    buses_500kv.csv                              (output de script 01)
    lineas_alta_tension.geojson                  (GeoSADI)
Outputs:
    buses_500kv.csv                              (actualizado si hay buses nuevos)
    lines_500kv.csv

Logica:
    Paso A — match por nombre con diccionario de aliases.
             Si encuentra 2 buses se confia en el resultado sin importar distancia geometrica
             (la geometria GeoSADI puede tener extremos desordenados).

    Paso B — snap geometrico solo para lineas que Paso A no pudo resolver.
             Si un extremo no matchea ningun bus conocido, se crea un bus nuevo
             en esa coordenada con nombre derivado del nombre de la linea.

Ejecutar desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/02_build_500kv_lines.py
"""

import json
import csv
import os
import re
import math
import unicodedata

# ── Rutas ──────────────────────────────────────────────────────────────────────
BUSES_CSV     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_500kv.csv"
INPUT_GEOJSON = "/mnt/c/Work/pypsa-ar-sandbox/Official data/GEOSADI/GEOJSON/lineas_alta_tension.geojson"
OUTPUT_LINES  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/lines_500kv.csv"

UMBRAL_SNAP_KM = 1.0  # distancia maxima para snap geometrico (Paso B)

# ── LINEAS INTERNACIONALES ─────────────────────────────────────────────────────
# Excluidas del modelo. Borrar entradas individuales si se desea incluir alguna.
EXCLUIR_NOMBRES = {
    'RINCON - LIMITE ARG-BRA 500 1',
    'RINCON - LIMITE ARG-BRA 500 2',
    'SGDE. ARG - CH SALTO GRANDE 500 1',
    'SGDE. ARG - CH SALTO GRANDE 500 2',
    'SGDE. ARG - CH SALTO GRANDE 500 3',
    'SGDE. ARG - CH SALTO GRANDE 500 4',
    'SGDE.ARG SGDE.URU 500 1',
    'SALTO GRANDE URG - TR6',
    'SALTO GRANDE URG - TR4',
    'SALTO GRANDE URG - TR5',
    'SALTO GRANDE URG - TR8',
    'COLONIA ELIA - S.JAVIER (UTE) 500',
}
# ──────────────────────────────────────────────────────────────────────────────

# ── DICCIONARIO DE ALIASES ─────────────────────────────────────────────────────
ALIASES = {
    'CPIEDRABUENA' : 'PIEDRA_BUENA',
    'CPBUENA'      : 'PIEDRA_BUENA',
    'CTPBUENA'     : 'CTPBUENA',
    'BBLANCA'      : 'BAHIA_BLANCA',
    'BAHIA_BLANCA' : 'BAHIA_BLANCA',
    'NPMADRYN'     : 'PUERTO_MADRYN',
    'PPATRIA'      : 'PASO_LA_PATRIA',
    'MALVINCO'     : 'MALVINAS',
    'RGRANDE'      : 'RIO_GRANDE',
    'LUJANSL'      : 'LUJAN',
    'GRAN_MZA'     : 'GRAN_MENDOZA',
    'ACAJON'       : 'AGUA_DE_CAJON',
    'AGUA_CAJON'   : 'AGUA_DE_CAJON',
    'LOMA_LATA'    : 'LOMA_LA_LATA',
    'CCOSTA'       : 'CERRITO_DE_LA_COSTA',
    'C_COSTA'      : 'CERRITO_DE_LA_COSTA',
    'CHOCON_OESTE' : 'EL_CHOCON_OESTE',
    'CHOCONOE'     : 'EL_CHOCON_OESTE',
    'CHCHOCON'     : 'EL_CHOCON_CH',
    'C_H_CHOCON'   : 'EL_CHOCON_CH',
    'CHOCON'       : 'EL_CHOCON',
    'ETPAGUILA'    : 'P_DEL_AGUILA',
    'ET_P_AGUILA'  : 'P_DEL_AGUILA',
    'CPAGUILA'     : 'P_DEL_AGUILA_CH',
    'C_P_AGUILA'   : 'P_DEL_AGUILA_CH',
    'PPLEUFU'      : 'P_P_LEUFU',
    'GRODRIGUEZ'   : 'GRAL_RODRIGUEZ',
    'G_RODRIGUEZ'  : 'GRAL_RODRIGUEZ',
    'NCAMPANA'     : 'NUEVA_CAMPANA',
    'N_CAMPANA'    : 'NUEVA_CAMPANA',
    'CELIA'        : 'C_ELIA',
    'C_ELIA'       : 'C_ELIA',
    'COLONIA_ELIA' : 'C_ELIA',
    'MBELGRANO'    : 'MANUEL_BELGRANO',
    'M_BELGRANO'   : 'MANUEL_BELGRANO',
    'GENELBA'      : 'CENTRAL_GENELBA',
    'SGDEARG'      : 'SALTO_GRANDE_ARG',
    'SGDE_ARG'     : 'SALTO_GRANDE_ARG',
    'STOME'        : 'SANTO_TOME',
    'S_TOME'       : 'SANTO_TOME',
    'ROESTE'       : 'ROSARIO_OESTE',
    'R_OESTE'      : 'ROSARIO_OESTE',
    'RINCON'       : 'RINCON_STA_MARIA',
    'AESPARANA'    : 'AES_PARANA',
    'GBROWN'       : 'G_BROWN',
    'CT_G_BROWN'   : 'G_BROWN',
    'STGO_DEL_ESTERO': 'SANTIAGO',
    'PBANDERITA'   : 'P_BANDERITA',
    'P_BANDERITA'  : 'P_BANDERITA',
    'CN_TSE'       : 'CN_TSE',
    'TERMINAL_SEIS': None,           # 132kV — ignorar como bus 500kV
    'PI608_CHOELE' : 'PI608_CHOELE',
    'PI608_BBLANCA': 'PI608_BBLANCA',
}
# ──────────────────────────────────────────────────────────────────────────────


def normalizar(s):
    s = s.strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.upper().replace(' ', '_').replace('-', '_')
    s = ''.join(c for c in s if c.isalnum() or c == '_')
    while '__' in s:
        s = s.replace('__', '_')
    return s.strip('_')


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def get_endpoints(geom):
    """Primer y ultimo punto de la geometria. No asume orden correcto (GeoSADI puede estar desordenado)."""
    if geom is None:
        return None, None
    if geom['type'] == 'LineString':
        c = geom['coordinates']
        return (c[0], c[-1]) if len(c) >= 2 else (None, None)
    elif geom['type'] == 'MultiLineString':
        parts = geom['coordinates']
        return (parts[0][0], parts[-1][-1]) if parts else (None, None)
    return None, None


def geom_to_wkt(geom):
    """GeoJSON geometry → WKT para columna geometry (carga directa en QGIS)."""
    if geom is None:
        return ''
    if geom['type'] == 'LineString':
        coords = ', '.join(f"{c[0]} {c[1]}" for c in geom['coordinates'])
        return f"LINESTRING ({coords})"
    elif geom['type'] == 'MultiLineString':
        parts = ['(' + ', '.join(f"{c[0]} {c[1]}" for c in p) + ')' for p in geom['coordinates']]
        return f"MULTILINESTRING ({', '.join(parts)})"
    return ''


def limpiar_num(s):
    """Limpia campos con coma decimal europea y unidades. Ej: ',02182 Ohm/km' → 0.02182"""
    if not s:
        return None
    m = re.match(r'^([0-9,\.]+)', str(s).strip())
    if not m:
        return None
    n = m.group(1)
    if ',' in n and '.' not in n:
        n = n.replace(',', '.')
    if n.startswith('.'):
        n = '0' + n
    try:
        return float(n)
    except ValueError:
        return None


def resolver_token(token, buses):
    if token in buses:
        return token
    if token in ALIASES:
        return ALIASES[token]
    return 'NO_MATCH'


def match_por_nombre(nombre, buses):
    """
    Busca 2 buses en el nombre normalizado de la linea usando buses directos y aliases.
    Si encuentra 2 buses el resultado es definitivo — no se valida contra geometria.
    """
    norm = re.sub(r'_500(_\d+)?$', '', normalizar(nombre))
    tokens = norm.split('_')
    candidatos = []
    for size in range(4, 0, -1):
        for i in range(len(tokens) - size + 1):
            token = '_'.join(tokens[i:i+size])
            r = resolver_token(token, buses)
            if r != 'NO_MATCH':
                candidatos.append((i, i+size, r))
    candidatos.sort(key=lambda x: -(x[1]-x[0]))
    sel = []
    used = set()
    for ini, fin, bid in candidatos:
        pos = set(range(ini, fin))
        if not pos & used:
            sel.append(bid)
            used |= pos
    sel = [b for b in sel if b is not None]
    return (sel[0], sel[1]) if len(sel) >= 2 else None


def snap_geometrico(ep, buses, umbral_km):
    mejor = None
    mejor_d = float('inf')
    for bid, bd in buses.items():
        d = haversine_km(ep[0], ep[1], bd['lon'], bd['lat'])
        if d < mejor_d:
            mejor_d = d
            mejor = bid
    return (mejor, mejor_d) if mejor_d <= umbral_km else (None, mejor_d)


def cargar_buses(csv_path):
    buses = {}
    with open(csv_path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            buses[row['bus_id']] = {
                'nombre': row['nombre'],
                'lon':    float(row['lon']),
                'lat':    float(row['lat']),
                'v_nom':  int(row['v_nom']),
            }
    return buses


def guardar_buses(csv_path, buses):
    campos = ['bus_id', 'nombre', 'lon', 'lat', 'v_nom']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for bid, bd in buses.items():
            writer.writerow({
                'bus_id': bid,
                'nombre': bd['nombre'],
                'lon':    round(bd['lon'], 7),
                'lat':    round(bd['lat'], 7),
                'v_nom':  bd['v_nom'],
            })


def main():
    print(f"Cargando buses: {BUSES_CSV}")
    buses = cargar_buses(BUSES_CSV)
    print(f"  Buses cargados: {len(buses)}")

    print(f"Cargando lineas: {INPUT_GEOJSON}")
    with open(INPUT_GEOJSON, encoding='utf-8') as f:
        lin_data = json.load(f)
    lin_500 = [f for f in lin_data['features'] if str(f['properties'].get('Tension','')).strip() == '500']
    print(f"  Lineas 500kV en archivo: {len(lin_500)}")
    print()

    lineas_out = []
    buses_nuevos = {}
    conteo = {'nombre_exacto': 0, 'snap_geometrico': 0, 'sin_resolver': 0, 'excluida': 0}

    for feat in lin_500:
        props  = feat['properties']
        nombre = props['Nombre'].strip()
        geom   = feat['geometry']

        if nombre in EXCLUIR_NOMBRES:
            conteo['excluida'] += 1
            continue

        longitud_km = limpiar_num(props.get('Longitud', ''))
        r_ohm_km    = limpiar_num(props.get('R', ''))
        x_ohm_km    = limpiar_num(props.get('X', ''))
        b_us_km     = limpiar_num(props.get('B', ''))
        r_ohm = round(r_ohm_km * longitud_km, 6) if r_ohm_km and longitud_km else None
        x_ohm = round(x_ohm_km * longitud_km, 6) if x_ohm_km and longitud_km else None
        b_us  = round(b_us_km  * longitud_km, 6) if b_us_km  and longitud_km else None

        ep0, ep1 = get_endpoints(geom)
        wkt = geom_to_wkt(geom)
        metodo = None
        bus0 = bus1 = None

        # Paso A — match por nombre
        match = match_por_nombre(nombre, buses)
        if match:
            bus0, bus1 = match
            metodo = 'nombre_exacto'
            conteo['nombre_exacto'] += 1

        # Paso B — snap geometrico
        if metodo is None:
            if ep0 is None or ep1 is None:
                conteo['sin_resolver'] += 1
                metodo = 'sin_resolver'
            else:
                sb0, sd0 = snap_geometrico(ep0, buses, UMBRAL_SNAP_KM)
                sb1, sd1 = snap_geometrico(ep1, buses, UMBRAL_SNAP_KM)
                nid = re.sub(r'_500(_\d+)?$', '', normalizar(nombre))
                if sb0 and not sb1:
                    nuevo = f"NUEVO_{nid}_B"
                    buses_nuevos[nuevo] = {'nombre': nuevo, 'lon': ep1[0], 'lat': ep1[1], 'v_nom': 500}
                    buses[nuevo] = buses_nuevos[nuevo]
                    bus0, bus1 = sb0, nuevo
                    metodo = 'snap_geometrico'; conteo['snap_geometrico'] += 1
                elif sb1 and not sb0:
                    nuevo = f"NUEVO_{nid}_A"
                    buses_nuevos[nuevo] = {'nombre': nuevo, 'lon': ep0[0], 'lat': ep0[1], 'v_nom': 500}
                    buses[nuevo] = buses_nuevos[nuevo]
                    bus0, bus1 = nuevo, sb1
                    metodo = 'snap_geometrico'; conteo['snap_geometrico'] += 1
                elif sb0 and sb1:
                    bus0, bus1 = sb0, sb1
                    metodo = 'snap_geometrico'; conteo['snap_geometrico'] += 1
                else:
                    conteo['sin_resolver'] += 1
                    metodo = 'sin_resolver'

        lineas_out.append({
            'line_name'         : normalizar(nombre),
            'nombre'            : nombre,
            'bus0'              : bus0 or '',
            'bus1'              : bus1 or '',
            'metodo'            : metodo,
            'longitud_km'       : longitud_km if longitud_km is not None else '',
            'r_ohm_km'          : r_ohm_km if r_ohm_km is not None else '',
            'x_ohm_km'          : x_ohm_km if x_ohm_km is not None else '',
            'b_us_km'           : b_us_km if b_us_km is not None else '',
            'r_ohm'             : r_ohm if r_ohm is not None else '',
            'x_ohm'             : x_ohm if x_ohm is not None else '',
            'b_us'              : b_us if b_us is not None else '',

            'geometry'          : wkt,
        })

    # ── Reporte ────────────────────────────────────────────────────────────────
    print("=== RESULTADO ===")
    for k, v in conteo.items():
        print(f"  {k:<20}: {v}")

    if buses_nuevos:
        print(f"\n  Buses nuevos agregados ({len(buses_nuevos)}):")
        for bid, bd in buses_nuevos.items():
            print(f"    {bid:<40} ({bd['lon']:.5f}, {bd['lat']:.5f})")

    sin_res = [l for l in lineas_out if l['metodo'] == 'sin_resolver']
    if sin_res:
        print(f"\n  ADVERTENCIA — Lineas sin resolver ({len(sin_res)}):")
        for l in sin_res:
            print(f"    '{l['nombre']}'")

    # ── Exportar ───────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_LINES), exist_ok=True)

    if buses_nuevos:
        guardar_buses(BUSES_CSV, buses)
        print(f"\n  buses_500kv.csv actualizado.")

    campos = [
        'line_id', 'line_name', 'nombre', 'bus0', 'bus1', 'metodo',
        'longitud_km', 'r_ohm_km', 'x_ohm_km', 'b_us_km',
        'r_ohm', 'x_ohm', 'b_us',

        'geometry',
    ]
    # Agregar line_id numerico correlativo
    for i, row in enumerate(lineas_out, start=1):
        row['line_id'] = i

    with open(OUTPUT_LINES, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(lineas_out)

    print(f"\n  lines_500kv.csv: {len(lineas_out)} lineas → {OUTPUT_LINES}")
    print()
    print("Listo.")


if __name__ == '__main__':
    main()
