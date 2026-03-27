"""
18_diagnostico_costos_marginales.py
Diagnostico de cobertura de costos marginales para generators_2024.csv.

Verifica que generadores de generators_2024.csv tienen costo marginal disponible
en los archivos de CAMMESA, separando por tipo de tecnologia.

Grupos de analisis:

    - Hidro       : datos pendientes, no se busca match
    - Termica y nuclear : match contra CVP_Termica.csv con logica de seleccion de combustible
                    Filtro: Año inicio=2026, Semana inicio=1
                    Match directo por clave reducida: primeras 4 siglas + ultimos 2 digitos
                    Prioridad de combustible:
                        1) GN
                        2) si no hay GN y hay un solo tipo_comb, usar ese
                        3) si solo estan FO y GO, usar FO
                    Si no hay match directo:
                        rescate por promedio usando primeras 6 siglas
    - Renovables  : match por nombre_geosadi vs columna Proyecto en CVP_renovar.csv
                    Se normaliza Proyecto eliminando tildes y llevando a mayusculas

Inputs:
    data/network_500kv/generators_2024.csv
    Official data/marginal_cost/CVP_Termica.csv
    Official data/marginal_cost/CVP_renovar.csv

Output:
    data/network_500kv/costos_marginales_diagnostico.csv

    Columnas:
        bus_name_origen, nombre_geosadi, nemo, carrier, p_nom,
        costo_marginal_match, fuente_costo, CVP_manual

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/18_diagnostico_costos_marginales.py
"""

import os
import sys
import unicodedata
import pandas as pd

# =============================================================================
# CONFIGURACION
# =============================================================================

GEN_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_2024.csv"
TERMICA_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/marginal_cost/CVP_Termica.csv"
RENOVAR_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/marginal_cost/CVP_renovar.csv"
OUTPUT_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/costos_marginales_diagnostico.csv"


CARRIERS_HIDRO = {"hydro", "pumped_hydro"}
CARRIERS_TERMICA = {"ocgt", "ccgt", "steam", "diesel", "nuclear"}
CARRIERS_RENOVAR = {"wind", "solar", "biomass", "biogas"}

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def normalizar_texto(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def clave_termica_reducida(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    if len(s) < 6:
        return s
    return s[:4] + s[-2:]


def prefijo_6(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    return s[:6]


def seleccionar_tipo_comb(grp):
    tipos = sorted(
        t for t in grp["tipo_comb"].dropna().astype(str).str.strip().str.upper().unique()
        if t != ""
    )

    if "GN" in tipos:
        return "GN"

    if len(tipos) == 1:
        return tipos[0]

    if set(tipos) == {"FO", "GO"}:
        return "FO"

    return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("18_diagnostico_costos_marginales.py")
    print("=" * 60)

    for f in [GEN_FILE, TERMICA_FILE, RENOVAR_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado: {f}")
            sys.exit(1)

    # =========================================================================
    # PASO 1 — Leer generators_2024
    # =========================================================================

    gen = pd.read_csv(GEN_FILE)

    cols_base = ["bus_name_origen", "nombre_geosadi", "nemo", "carrier", "p_nom"]
    gen = gen[cols_base].copy()

    gen["costo_marginal_match"] = "NO"
    gen["fuente_costo"] = ""
    gen["CVP_manual"] = ""

    print(f"\nUnidades totales: {len(gen)}")

    # =========================================================================
    # PASO 2 — Preparar CVP termica
    # =========================================================================

    termica_raw = pd.read_csv(TERMICA_FILE, encoding="latin-1")
    termica_raw.columns = termica_raw.columns.str.strip()

    termica = termica_raw[
        (termica_raw["Año inicio"] == 2026) &
        (termica_raw["Semana inicio"] == 1)
    ].copy()

    termica["Maquina"] = termica["Máquina"].astype(str).str.strip().str.upper()
    termica["clave_termica"] = termica["Maquina"].apply(clave_termica_reducida)
    termica["prefijo_6"] = termica["Maquina"].apply(prefijo_6)
    termica["tipo_comb"] = termica["Tipo_Comb"].astype(str).str.strip().str.upper()

    termica_lookup = {}
    termica_promedio_lookup = {}

    for clave, grp in termica.groupby("clave_termica"):
        tipo_sel = seleccionar_tipo_comb(grp)

        if tipo_sel is None:
            continue

        grp_sel = grp[grp["tipo_comb"] == tipo_sel].copy()
        fila_sel = grp_sel.sort_values("CVP_Total_Utilizado").iloc[0]

        termica_lookup[clave] = {
            "tipo_comb": tipo_sel,
            "costo": fila_sel["CVP_Total_Utilizado"],
            "maquina": fila_sel["Maquina"],
        }

    for pref6, grp in termica.groupby("prefijo_6"):
        tipo_sel = seleccionar_tipo_comb(grp)

        if tipo_sel is None:
            continue

        grp_sel = grp[grp["tipo_comb"] == tipo_sel].copy()

        termica_promedio_lookup[pref6] = {
            "tipo_comb": tipo_sel,
            "costo_promedio": grp_sel["CVP_Total_Utilizado"].mean(),
        }

    # =========================================================================
    # PASO 3 — Preparar CVP renovar
    # =========================================================================

    renovar_raw = pd.read_csv(RENOVAR_FILE, encoding="latin-1")
    renovar_raw.columns = renovar_raw.columns.str.strip()

    renovar_raw["Proyecto_norm"] = renovar_raw["Proyecto"].apply(normalizar_texto)
    proyectos_renovar = set(renovar_raw["Proyecto_norm"])

    # =========================================================================
    # PASO 4 — Match
    # =========================================================================

    match_termica = 0
    match_renovar = 0
    pendientes = 0

    for idx, row in gen.iterrows():
        carrier = row["carrier"]

        if  carrier in CARRIERS_HIDRO:
            gen.at[idx, "costo_marginal_match"] = "PENDIENTE"
            pendientes += 1
            continue

        if carrier in CARRIERS_TERMICA:
            clave = clave_termica_reducida(row["bus_name_origen"])
            pref6 = prefijo_6(row["bus_name_origen"])

            if clave in termica_lookup:
                gen.at[idx, "costo_marginal_match"] = "SI"
                gen.at[idx, "fuente_costo"] = "CVP_TERMICA"
                match_termica += 1

            elif pref6 in termica_promedio_lookup:
                gen.at[idx, "costo_marginal_match"] = "SI"
                gen.at[idx, "fuente_costo"] = "CVP_TERMICA_PROMEDIO"
                match_termica += 1

        elif carrier in CARRIERS_RENOVAR:
            nombre = str(row["nombre_geosadi"]).strip().upper()

            if nombre in proyectos_renovar:
                gen.at[idx, "costo_marginal_match"] = "SI"
                gen.at[idx, "fuente_costo"] = "CVP_RENOVAR"
                match_renovar += 1

    # =========================================================================
    # PASO 5 — Reporte
    # =========================================================================

    total_si = (gen["costo_marginal_match"] == "SI").sum()
    total_no = (gen["costo_marginal_match"] == "NO").sum()
    total_pend = (gen["costo_marginal_match"] == "PENDIENTE").sum()

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Con costo     : {total_si}")
    print(f"  Sin costo     : {total_no}")
    print(f"  Pendientes    : {total_pend}")
    print(f"  Termica match : {match_termica}")
    print(f"  Renovar match : {match_renovar}")
    print("=" * 60)

    # =========================================================================
    # PASO 6 — Exportar
    # =========================================================================

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    gen.to_csv(OUTPUT_FILE, index=False)

    print(f"\nOutput: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()