"""
12_build_generators_final.py
Une generators_readypypsa.csv con los generadores resueltos manualmente de
generators_manualpypsa.csv para producir generators_final.csv — la tabla
definitiva de generadores que entra a PyPSA.

Inputs:
    data/network_500kv/generators_readypypsa.csv   (script 11)
    data/network_500kv/generators_manualpypsa.csv  (completado manualmente)

Output:
    data/network_500kv/generators_final.csv
        Una fila por generador. Contiene todos los generadores con
        nombre_geosadi Y bus_conexion500kv resueltos.
        Es el input del modelo junto con buses_final.csv y lines_500kv_final.csv.

        Columna 'stat': estado del generador en el snapshot PSS/E (pico verano 25/26).
        stat=1 en servicio, stat=0 fuera de servicio en ese caso base.
        Usar como punto de partida para decidir que centrales cargar en PyPSA.
        Modificar manualmente si se quiere forzar el encendido o apagado de una central.

        Columna 'control': tipo de control del generador en el power flow.
            PV  — el generador controla potencia activa (P) y mantiene tension (V)
                  en su bus mediante el regulador de tension (AVR). Es el modo
                  de operacion tipico de centrales termicas, hidro y nuclear.
            PQ  — el generador inyecta potencia activa (P) y reactiva (Q) fijas,
                  sin regular tension. Corresponde a generacion renovable variable
                  (solar, eolica) que conecta a traves de inversores y no tiene AVR.
            Slack — un unico bus de referencia que fija el angulo (0 grados) y
                  absorbe el desbalance de potencia activa que queda despues de
                  resolver el power flow. Ver SLACK_BUS en 12c_test_snapshot.py.

        Asignacion de control por carrier:
            PV  : nuclear, hydro, pumped_hydro, ccgt, ocgt, steam, biomass, biogas, diesel
            PQ  : solar, wind

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/12_build_generators_final.py
"""

import os
import sys
import pandas as pd

# =============================================================================
# CONFIGURACION
# =============================================================================

READY_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_readypypsa.csv"
MANUAL_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_manualpypsa.csv"
OUTPUT_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "generators_final.csv")

COLS = [
    'gen_key', 'bus_name_origen', 'nombre_geosadi',
    'bus_conexion500kv', 'bus_conexion500kv_name',
    'carrier', 'lat', 'lon',
    'pg_mw', 'pt_mw', 'stat',
    'match_type', 'n_saltos', 'camino',
]

# Carriers que regulan tension (AVR) -> PV
# Carriers que no regulan tension (inversores) -> PQ
CARRIERS_PV = {'nuclear', 'hydro', 'pumped_hydro', 'ccgt', 'ocgt', 'steam',
               'biomass', 'biogas', 'diesel'}
CARRIERS_PQ = {'solar', 'wind'}


def assign_control(carrier):
    if carrier in CARRIERS_PV:
        return 'PV'
    elif carrier in CARRIERS_PQ:
        return 'PQ'
    else:
        return 'PQ'  # por defecto conservador si carrier desconocido


def main():
    print("=" * 60)
    print("12_build_generators_final.py -- tabla definitiva PyPSA")
    print("=" * 60)

    for f in [READY_FILE, MANUAL_FILE]:
        if not os.path.isfile(f):
            print("[ERROR] Archivo no encontrado:")
            print("  " + f)
            sys.exit(1)

    ready  = pd.read_csv(READY_FILE)
    manual = pd.read_csv(MANUAL_FILE)

    print("generators_readypypsa  : " + str(len(ready)) + " generadores")
    print("generators_manualpypsa : " + str(len(manual)) + " generadores")

    # Filtrar manual: solo falta='ok' y match_type != 'sin_conexion'
    mask      = (manual['falta'] == 'ok') & (manual['match_type'] != 'sin_conexion')
    manual_ok = manual[mask].copy()

    n_captivos = len(manual[(manual['falta'] == 'ok') & (manual['match_type'] == 'sin_conexion')])
    n_pending  = len(manual[manual['falta'] != 'ok'])

    print("\n  Resueltos desde manual : " + str(len(manual_ok)))
    print("  Captivos excluidos     : " + str(n_captivos) + "  (ALUAR, El Trapial, autoproduccion)")
    print("  Aun sin resolver       : " + str(n_pending))

    # Alinear columnas
    manual_ok = manual_ok[COLS].copy()
    ready_out = ready[COLS].copy()

    df_final = pd.concat([ready_out, manual_ok], ignore_index=True)
    df_final = df_final.sort_values('pt_mw', ascending=False).reset_index(drop=True)

    # Agregar columna control
    df_final['control'] = df_final['carrier'].apply(assign_control)

    # ==========================================================
    # REPORTE
    # ==========================================================
    print("\n" + "=" * 60)
    print("GENERATORS_FINAL")
    print("=" * 60)
    print("  Total generadores : " + str(len(df_final)))

    mw_total = df_final[df_final['pt_mw'] < 9000]['pt_mw'].sum()
    print("  Potencia total    : " + str(round(mw_total, 1)) + " MW  (excluye PT=9999)")

    print("\n  Por carrier (pt < 9999):")
    activos = df_final[df_final['pt_mw'] < 9990]
    for carrier, grp in activos.groupby('carrier'):
        ctrl = assign_control(carrier)
        print("  " + str(carrier).ljust(15) + ": " +
              str(len(grp)).rjust(4) + " gen  " +
              str(round(grp['pt_mw'].sum(), 1)).rjust(10) + " MW  control=" + ctrl)

    print("\n  Por match_type:")
    for mt, grp in df_final.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9000]['pt_mw'].sum()
        print("  " + str(mt).ljust(15) + ": " +
              str(len(grp)).rjust(4) + " gen  " +
              str(round(mw, 1)).rjust(10) + " MW")

    n_sin_coord = df_final['lat'].isna().sum()
    if n_sin_coord > 0:
        print("\n  Sin coordenadas: " + str(n_sin_coord) + " generadores (entran a PyPSA sin punto en el mapa)")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False)
    print("\n✔ " + OUTPUT_FILE + "  (" + str(len(df_final)) + " filas)")
    print("\nProximo: 12b_export_qgis_generators.py")


if __name__ == "__main__":
    main()
