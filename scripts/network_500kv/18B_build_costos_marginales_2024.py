"""
18B_build_costos_marginales_2024.py
Construye la tabla final de costos marginales fijos anuales 2024 por generadora.

Lee generators_2024.csv y el archivo completado manualmente
costos_marginales_diagnostico_completado.csv, reconstruye los costos marginales
desde los archivos CVP de CAMMESA y aplica overrides manuales cuando existen.

Fuentes de costo:
    - CVP_Termica.csv
        Costo unico por unidad.
        Filtro: Año inicio=2026, Semana inicio=1

      - CVP_renovar.csv
        Costo fijo anual = promedio simple de Jan-24 ... Dec-24
       
    - CVP_manual
        Si CVP_manual es numerico:
            usar directamente ese valor como costo marginal
        Si CVP_manual es texto:
            buscar ese nombre en el CVP que corresponda:
                termica/nuclear -> CVP_Termica
                renovables/hydro/pumped_hydro -> CVP_renovar

Inputs:
    data/network_500kv/generators_2024.csv
    data/network_500kv/costos_marginales_diagnostico_completado.csv
    Official data/marginal_cost/CVP_Termica.csv (archivo externo a github)
    Official data/marginal_cost/CVP_renovar.csv (archivo externo a github)

Output:
    data/network_500kv/costos_marginales_2024.csv

    Columnas:
        gen_key, bus_name_origen, nombre_geosadi, nemo,
        bus_conexion500kv, bus_conexion500kv_name,
        carrier, p_nom, lat, lon,
        costo_marginal(USD/mwh)

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/18B_build_costos_marginales_2024.py
"""

import os
import sys
import unicodedata
import numpy as np
import pandas as pd

# =============================================================================
# CONFIGURACION
# =============================================================================

GEN_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_2024.csv"
DIAG_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/costos_marginales_diagnostico_completado.csv"
TERMICA_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/marginal_cost/CVP_Termica.csv"
RENOVAR_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/marginal_cost/CVP_renovar.csv"

OUTPUT_DIR = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "costos_marginales_2024.csv")

CARRIERS_TERMICA = {"ocgt", "ccgt", "steam", "diesel", "nuclear"}
CARRIERS_RENOVAR = {"wind", "solar", "biomass", "biogas"}
CARRIERS_HIDRO = {"hydro", "pumped_hydro"}

MONTH_COLS_2024 = [
    "Jan-24", "Feb-24", "Mar-24", "Apr-24", "May-24", "Jun-24",
    "Jul-24", "Aug-24", "Sep-24", "Oct-24", "Nov-24", "Dec-24",
]

COLS_OUT = [
    "gen_key", "bus_name_origen", "nombre_geosadi", "nemo",
    "bus_conexion500kv", "bus_conexion500kv_name",
    "carrier", "p_nom", "lat", "lon",
    "costo_marginal(USD/mwh)",
]

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


def parsear_numero(s):
    if pd.isna(s):
        return np.nan
    s = str(s).strip()
    if s == "":
        return np.nan
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


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
        t for t in grp["Tipo_Comb"].dropna().astype(str).str.strip().str.upper().unique()
        if t != ""
    )

    if "GN" in tipos:
        return "GN"

    if len(tipos) == 1:
        return tipos[0]

    if set(tipos) == {"FO", "GO"}:
        return "FO"

    return None


def construir_lookup_termica(termica):
    lookup_directo = {}
    lookup_promedio = {}
    lookup_maquina = {}

    for maquina, grp in termica.groupby("Maquina"):
        tipo_sel = seleccionar_tipo_comb(grp)
        if tipo_sel is None:
            continue

        grp_sel = grp[grp["Tipo_Comb"] == tipo_sel].copy()
        fila_sel = grp_sel.sort_values("CVP_Total_Utilizado").iloc[0]

        lookup_maquina[maquina] = {
            "tipo_comb": tipo_sel,
            "costo": float(fila_sel["CVP_Total_Utilizado"]),
        }

    for clave, grp in termica.groupby("clave_termica"):
        tipo_sel = seleccionar_tipo_comb(grp)
        if tipo_sel is None:
            continue

        grp_sel = grp[grp["Tipo_Comb"] == tipo_sel].copy()
        fila_sel = grp_sel.sort_values("CVP_Total_Utilizado").iloc[0]

        lookup_directo[clave] = {
            "tipo_comb": tipo_sel,
            "costo": float(fila_sel["CVP_Total_Utilizado"]),
        }

    for pref6, grp in termica.groupby("prefijo_6"):
        tipo_sel = seleccionar_tipo_comb(grp)
        if tipo_sel is None:
            continue

        grp_sel = grp[grp["Tipo_Comb"] == tipo_sel].copy()

        lookup_promedio[pref6] = {
            "tipo_comb": tipo_sel,
            "costo": float(grp_sel["CVP_Total_Utilizado"].mean()),
        }

    return lookup_maquina, lookup_directo, lookup_promedio


def construir_lookup_renovar(renovar):
    renovar = renovar.copy()
    renovar["Proyecto_norm"] = renovar["Proyecto"].apply(normalizar_texto)

    for col in MONTH_COLS_2024:
        renovar[col] = pd.to_numeric(renovar[col], errors="coerce")

    renovar["costo_promedio_2024"] = renovar[MONTH_COLS_2024].mean(axis=1, skipna=True)

    lookup = (
        renovar.groupby("Proyecto_norm", as_index=False)["costo_promedio_2024"]
        .mean()
        .set_index("Proyecto_norm")["costo_promedio_2024"]
        .to_dict()
    )

    return lookup


def resolver_costo_termica_automatico(bus_name_origen, lookup_directo, lookup_promedio):
    clave = clave_termica_reducida(bus_name_origen)
    pref6 = prefijo_6(bus_name_origen)

    if clave in lookup_directo:
        return float(lookup_directo[clave]["costo"]), "CVP_TERMICA"

    if pref6 in lookup_promedio:
        return float(lookup_promedio[pref6]["costo"]), "CVP_TERMICA_PROMEDIO"

    return np.nan, ""


def resolver_costo_termica_manual(maquina_manual, lookup_maquina):
    maquina = str(maquina_manual).strip().upper()
    if maquina in lookup_maquina:
        return float(lookup_maquina[maquina]["costo"]), "CVP_TERMICA"
    return np.nan, ""


def resolver_costo_renovar(nombre_manual, lookup_renovar):
    proyecto = normalizar_texto(nombre_manual)
    if proyecto in lookup_renovar:
        return float(lookup_renovar[proyecto]), "CVP_RENOVAR"
    return np.nan, ""


def merge_con_diagnostico(gen, diag):
    diag = diag.copy()

    if "gen_key" in diag.columns:
        return gen.merge(
            diag[["gen_key", "costo_marginal_match", "fuente_costo", "CVP_manual"]],
            on="gen_key",
            how="left",
        )

    merge_cols = [c for c in ["bus_name_origen", "nombre_geosadi", "nemo", "carrier", "p_nom"] if c in diag.columns]

    if len(merge_cols) == 0:
        print("[ERROR] No se encontraron columnas suficientes para merge con el diagnostico.")
        sys.exit(1)

    gen = gen.copy()
    diag = diag.copy()

    gen["_merge_idx"] = gen.groupby(merge_cols).cumcount()
    diag["_merge_idx"] = diag.groupby(merge_cols).cumcount()

    merged = gen.merge(
        diag[merge_cols + ["_merge_idx", "costo_marginal_match", "fuente_costo", "CVP_manual"]],
        on=merge_cols + ["_merge_idx"],
        how="left",
    )

    merged = merged.drop(columns="_merge_idx")
    return merged

# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("18B_build_costos_marginales_2024.py")
    print("=" * 60)

    for f in [GEN_FILE, DIAG_FILE, TERMICA_FILE, RENOVAR_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # =========================================================
    # CARGAR INPUTS
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    diag = pd.read_csv(DIAG_FILE, encoding="latin-1")
    termica = pd.read_csv(TERMICA_FILE, encoding="latin-1")
    renovar = pd.read_csv(RENOVAR_FILE, encoding="latin-1")

    termica.columns = termica.columns.str.strip()
    renovar.columns = renovar.columns.str.strip()

    gen = merge_con_diagnostico(gen, diag)

    if "costo_marginal_match" not in gen.columns:
        gen["costo_marginal_match"] = ""
    if "fuente_costo" not in gen.columns:
        gen["fuente_costo"] = ""
    if "CVP_manual" not in gen.columns:
        gen["CVP_manual"] = ""

    print(f"\nUnidades en generators_2024: {len(gen)}")

    # =========================================================
    # PREPARAR CVP TERMICA
    # =========================================================
    termica = termica[
        (termica["Año inicio"] == 2026) &
        (termica["Semana inicio"] == 1)
    ].copy()

    termica["Maquina"] = termica["Máquina"].astype(str).str.strip().str.upper()
    termica["Tipo_Comb"] = termica["Tipo_Comb"].astype(str).str.strip().str.upper()
    termica["clave_termica"] = termica["Maquina"].apply(clave_termica_reducida)
    termica["prefijo_6"] = termica["Maquina"].apply(prefijo_6)

    lookup_maquina, lookup_directo, lookup_promedio = construir_lookup_termica(termica)

    # =========================================================
    # PREPARAR CVP RENOVAR
    # =========================================================
    faltantes_months = [c for c in MONTH_COLS_2024 if c not in renovar.columns]
    if len(faltantes_months) > 0:
        print("[ERROR] Faltan columnas mensuales 2024 en CVP_renovar:")
        print("        " + ", ".join(faltantes_months))
        sys.exit(1)

    lookup_renovar = construir_lookup_renovar(renovar)

    # =========================================================
    # RESOLVER COSTOS
    # =========================================================
    costos = []
    fuentes = []

    for _, row in gen.iterrows():
        carrier = str(row["carrier"]).strip()
        manual_raw = row.get("CVP_manual", "")
        manual_num = parsear_numero(manual_raw)

        costo = np.nan
        fuente = ""

        # -----------------------------------------------------
        # 1. OVERRIDE MANUAL NUMERICO
        # -----------------------------------------------------
        if not pd.isna(manual_num):
            costo = float(manual_num)
            fuente = "CVP_MANUAL"

        # -----------------------------------------------------
        # 2. OVERRIDE MANUAL TEXTO
        # -----------------------------------------------------
        elif pd.notna(manual_raw) and str(manual_raw).strip() != "":
            manual_txt = str(manual_raw).strip()

            if carrier in CARRIERS_TERMICA:
                costo, fuente = resolver_costo_termica_manual(manual_txt, lookup_maquina)

            elif carrier in CARRIERS_RENOVAR or carrier in CARRIERS_HIDRO:
                costo, fuente = resolver_costo_renovar(manual_txt, lookup_renovar)

        # -----------------------------------------------------
        # 3. MATCH AUTOMATICO
        # -----------------------------------------------------
        if pd.isna(costo):
            if carrier in CARRIERS_TERMICA:
                costo, fuente = resolver_costo_termica_automatico(
                    row["bus_name_origen"], lookup_directo, lookup_promedio
                )

            elif carrier in CARRIERS_RENOVAR:
                costo, fuente = resolver_costo_renovar(row["nombre_geosadi"], lookup_renovar)

        costos.append(costo)
        fuentes.append(fuente)

    gen["costo_marginal(USD/mwh)"] = pd.to_numeric(costos, errors="coerce")
    gen["fuente_costo_final"] = fuentes

    # =========================================================
    # REPORTE
    # =========================================================
    con_costo = gen["costo_marginal(USD/mwh)"].notna().sum()

    pendientes = (
        gen["costo_marginal(USD/mwh)"].isna() &
        (gen["costo_marginal_match"].fillna("").astype(str).str.upper() == "PENDIENTE")
    ).sum()

    sin_costo = (
        gen["costo_marginal(USD/mwh)"].isna() &
        ~(gen["costo_marginal_match"].fillna("").astype(str).str.upper() == "PENDIENTE")
    ).sum()

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Con costo     : {con_costo}")
    print(f"  Sin costo     : {sin_costo}")
    print(f"  Pendientes    : {pendientes}")
    print("=" * 60)

    # =========================================================
    # EXPORTAR
    # =========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    out = gen[COLS_OUT].copy()
    out["costo_marginal(USD/mwh)"] = out["costo_marginal(USD/mwh)"].round(4)

    out.to_csv(OUTPUT_FILE, index=False)

    print(f"\nOutput: {OUTPUT_FILE}  ({len(out)} filas)")
    print("=" * 60)


if __name__ == "__main__":
    main()