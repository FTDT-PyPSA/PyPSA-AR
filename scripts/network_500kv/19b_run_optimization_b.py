"""
19b_run_optimization_b.py
Corre el despacho economico lineal DC (OPF) sobre la red 500 kV argentina
usando los perfiles de la variante B (gen_profiles_2024b.csv), donde hidro,
pumped_hydro y nuclear tienen p_max_pu limitado a su ENERG_OPERADA real 2024.

Diferencias respecto al script 19:
    - Input de perfiles: gen_profiles_2024b.csv (script 17b)
    - Wind, solar y nuclear con costo marginal forzado a 0
    - Sin p_min_pu en ningun generador

Inputs (versionados en GitHub):
    networks/network_500kv.nc
    data/network_500kv/generators_2024.csv
    data/network_500kv/loads_2024.csv
    data/network_500kv/costos_marginales_2024.csv

Inputs (externos a GitHub):
    Official data/gen_profiles_2024b.csv

Output:
    networks/results_2024b_YYYYMMDD_YYYYMMDD.nc

Decisiones de modelado:
    - DC OPF lineal: sin perdidas, sin tensiones, solo flujos activos.
    - Slack bus: ATUCHA 2_21kV.
    - Link Brasil: solo importacion (p_min_pu=0), libre para el solver.
    - Load shedding: LOAD_SHED_COST USD/MWh por bus, garantiza factibilidad.
    - Wind, solar, nuclear: costo marginal = 0 (el solver los despacha primero).
    - Hidro/pumped_hydro: p_max_pu = ENERG_OPERADA/p_nom, costo = 0.
    - Termica e importacion Brasil: costos marginales reales.
    - Generadores sin perfil en gen_profiles_2024b.csv: excluidos del network.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/19b_run_optimization_b.py
"""

import os
import sys
import pandas as pd
import numpy as np
import pypsa

# =============================================================================
# CONFIGURACION
# =============================================================================

NETWORK_FILE  = "/mnt/c/Work/pypsa-ar-base/networks/network_500kv.nc"
GEN_FILE      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_2024.csv"
LOADS_FILE    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/loads_2024.csv"
COSTOS_FILE   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/costos_marginales_2024.csv"
PROFILES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/gen_profiles_2024b.csv"
OUTPUT_DIR    = "/mnt/c/Work/pypsa-ar-base/networks"

# Periodo de simulacion
FECHA_INICIO  = "2024-02-01"
FECHA_FIN     = "2024-02-07"

# Chunking: None = un solo problema | 7 = semanal | 30 = mensual
CHUNK_DIAS    = None

# Generadores optimizables sin costo marginal
# False: costo_marginal = 0 | True: se excluyen
EXCLUIR_SIN_COSTO = False

# Carriers con costo marginal forzado a 0
# El solver los despacha antes que cualquier termica
CARRIERS_COSTO_CERO = {"wind", "solar", "nuclear"}

# Load shedding virtual por bus
LOAD_SHED_COST = 10_000.0
LOAD_SHED_PNOM = 99_999.0

SLACK_BUS    = "ATUCHA 2_21kV"
BRASIL_LINK  = "importacion_brasil"

BUSES_A_EXCLUIR_OPF = {"T PEPE", "PBUENA2", "PBUENA2_20kV"}

# Agrupaciones para el reporte
CARRIERS_TERMICA  = {"ocgt", "ccgt", "steam", "diesel"}
CARRIERS_HYDRO    = {"hydro", "pumped_hydro"}


# =============================================================================
# HELPERS
# =============================================================================

def verificar_inputs():
    archivos = {
        "network_500kv.nc"           : NETWORK_FILE,
        "generators_2024.csv"        : GEN_FILE,
        "loads_2024.csv"             : LOADS_FILE,
        "costos_marginales_2024.csv" : COSTOS_FILE,
        "gen_profiles_2024b.csv"     : PROFILES_FILE,
    }
    ok = True
    for nombre, ruta in archivos.items():
        if not os.path.isfile(ruta):
            print(f"  [ERROR] No encontrado: {nombre}")
            print(f"          Ruta esperada: {ruta}")
            ok = False
    if not ok:
        sys.exit(1)
    print("  Todos los inputs verificados.")


def nombre_output(fecha_ini, fecha_fin):
    ini = pd.Timestamp(fecha_ini).strftime("%Y%m%d")
    fin = pd.Timestamp(fecha_fin).strftime("%Y%m%d")
    return os.path.join(OUTPUT_DIR, f"results_2024b_{ini}_{fin}.nc")


def parsear_snapshots_csv(serie):
    return pd.to_datetime(serie, dayfirst=True, format="%d/%m/%Y %H:%M")


def solver_status_ok(status):
    if status is None:
        return False
    if isinstance(status, str):
        return status.strip().lower() in {"ok", "optimal"}
    if isinstance(status, (tuple, list)):
        status_norm = tuple(str(x).strip().lower() for x in status)
        return status_norm in {("ok",), ("optimal",), ("ok", "optimal"), ("optimal", "ok")}
    return str(status).strip().lower() in {"ok", "optimal"}


# =============================================================================
# PASO 1 — Cargar network base
# =============================================================================

def cargar_network():
    print("\n[1/6] Cargando network base ...")
    n = pypsa.Network(NETWORK_FILE)
    print(f"  Buses          : {len(n.buses)}")
    print(f"  Lineas         : {len(n.lines)}")
    print(f"  Transformadores: {len(n.transformers)}")
    print(f"  Links          : {len(n.links)}")

    if SLACK_BUS in n.buses.index:
        n.buses.loc[SLACK_BUS, "control"] = "Slack"
        print(f"  Slack bus      : {SLACK_BUS}")
    else:
        print(f"  [AVISO] Slack bus '{SLACK_BUS}' no encontrado")

    if BRASIL_LINK in n.links.index:
        n.links.loc[BRASIL_LINK, "p_min_pu"] = 0.0
        print(f"  Link Brasil    : p_min_pu=0 (solo importacion)")
    else:
        print(f"  [AVISO] Link '{BRASIL_LINK}' no encontrado")

    _excluir_buses_aislados(n)

    print(f"  Buses finales  : {len(n.buses)}")
    print(f"  Lineas finales : {len(n.lines)}")
    return n


def _excluir_buses_aislados(n):
    buses_presentes = [b for b in BUSES_A_EXCLUIR_OPF if b in n.buses.index]
    if not buses_presentes:
        return
    print(f"  Excluyendo buses aislados: {sorted(buses_presentes)}")

    for name in n.lines[n.lines["bus0"].isin(buses_presentes) | n.lines["bus1"].isin(buses_presentes)].index:
        n.remove("Line", name)
    for name in n.transformers[n.transformers["bus0"].isin(buses_presentes) | n.transformers["bus1"].isin(buses_presentes)].index:
        n.remove("Transformer", name)
    for name in n.links[n.links["bus0"].isin(buses_presentes) | n.links["bus1"].isin(buses_presentes)].index:
        n.remove("Link", name)
    for bus in buses_presentes:
        n.remove("Bus", bus)


# =============================================================================
# PASO 2 — Preparar snapshots
# =============================================================================

def preparar_snapshots():
    print(f"\n[2/6] Preparando snapshots ...")
    snapshots = pd.date_range(
        start = FECHA_INICIO,
        end   = pd.Timestamp(FECHA_FIN) + pd.Timedelta(hours=23),
        freq  = "h",
    )
    print(f"  Periodo  : {FECHA_INICIO}  ->  {FECHA_FIN}")
    print(f"  Snapshots: {len(snapshots)} horas")
    return snapshots


# =============================================================================
# PASO 3 — Agregar generadores
# =============================================================================

def agregar_generadores(n, snapshots):
    print(f"\n[3/6] Agregando generadores ...")

    gen  = pd.read_csv(GEN_FILE)
    cost = pd.read_csv(COSTOS_FILE)[["gen_key", "costo_marginal(USD/mwh)"]].copy()
    cost.rename(columns={"costo_marginal(USD/mwh)": "costo_marginal"}, inplace=True)
    gen  = gen.merge(cost, on="gen_key", how="left")

    # Forzar costo 0 a carriers definidos
    mask_cero = gen["carrier"].isin(CARRIERS_COSTO_CERO)
    gen.loc[mask_cero, "costo_marginal"] = 0.0
    print(f"  Costo=0 forzado: {mask_cero.sum()} generadores ({', '.join(sorted(CARRIERS_COSTO_CERO))})")

    # Generadores sin costo
    sin_costo   = gen["costo_marginal"].isna()
    n_sin_costo = sin_costo.sum()
    if EXCLUIR_SIN_COSTO:
        gen = gen[~sin_costo].copy()
        print(f"  {n_sin_costo} generadores sin costo excluidos")
    else:
        gen.loc[sin_costo, "costo_marginal"] = 0.0
        if n_sin_costo:
            print(f"  {n_sin_costo} generadores sin costo -> costo_marginal=0")

    buses_red     = set(n.buses.index)
    n_agregados   = 0
    n_bus_faltante = 0

    for _, row in gen.iterrows():
        bus = row.get("bus_conexion500kv_name")
        if pd.isna(bus) or bus not in buses_red:
            n_bus_faltante += 1
            continue
        n.add("Generator", row["gen_key"],
              bus=bus, p_nom=float(row["p_nom"]),
              carrier=row["carrier"],
              marginal_cost=float(row["costo_marginal"]))
        n_agregados += 1

    print(f"  Generadores agregados : {n_agregados}")
    if n_bus_faltante:
        print(f"  [AVISO] {n_bus_faltante} omitidos — bus no encontrado en el network")

    return gen[gen["bus_conexion500kv_name"].isin(buses_red)].copy()


# =============================================================================
# PASO 4 — Agregar perfiles p_max_pu desde gen_profiles_2024b.csv
# =============================================================================

def agregar_perfiles(n, snapshots):
    print(f"\n[4/6] Cargando perfiles (gen_profiles_2024b.csv) ...")

    chunks     = []
    ts_inicio  = snapshots[0]
    ts_fin     = snapshots[-1]

    for chunk in pd.read_csv(PROFILES_FILE, chunksize=500_000, low_memory=False):
        chunk["ts"] = parsear_snapshots_csv(chunk["datetime"])
        chunk = chunk[(chunk["ts"] >= ts_inicio) & (chunk["ts"] <= ts_fin)]
        if not chunk.empty:
            chunks.append(chunk[["gen_key", "ts", "p_max_pu"]])

    if not chunks:
        print("  [ERROR] No hay perfiles para el periodo configurado.")
        sys.exit(1)

    perfiles = pd.concat(chunks, ignore_index=True)
    perfiles_wide = perfiles.pivot_table(
        index="ts", columns="gen_key", values="p_max_pu", aggfunc="first"
    )
    perfiles_wide.index.name = None
    perfiles_wide = perfiles_wide.reindex(snapshots).fillna(0.0)

    gens_en_red  = set(n.generators.index)
    cols_validas = [c for c in perfiles_wide.columns if c in gens_en_red]
    perfiles_wide = perfiles_wide[cols_validas]

    n.generators_t.p_max_pu = perfiles_wide
    print(f"  Generadores con perfil : {len(cols_validas)}")

    gens_sin_perfil = gens_en_red - set(cols_validas)
    if gens_sin_perfil:
        for gkey in sorted(gens_sin_perfil):
            n.remove("Generator", gkey)
        print(f"  {len(gens_sin_perfil)} generadores sin perfil excluidos")


# =============================================================================
# PASO 5 — Agregar demanda horaria
# =============================================================================

def agregar_demanda(n, snapshots):
    print(f"\n[5/6] Cargando demanda horaria ...")

    loads = pd.read_csv(LOADS_FILE)
    loads["ts"] = parsear_snapshots_csv(loads["datetime"])
    ts_inicio = snapshots[0]
    ts_fin    = snapshots[-1]
    loads = loads[(loads["ts"] >= ts_inicio) & (loads["ts"] <= ts_fin)].copy()

    loads_wide = loads.pivot_table(
        index="ts", columns="bus_name", values="p_mw", aggfunc="sum"
    )
    loads_wide.index.name = None
    loads_wide = loads_wide.reindex(snapshots).fillna(0.0)

    buses_red = set(n.buses.index)
    n_cargas  = 0
    for bus_name in loads_wide.columns:
        if bus_name not in buses_red:
            continue
        n.add("Load", f"load_{bus_name}", bus=bus_name)
        n_cargas += 1

    load_names = [f"load_{b}" for b in loads_wide.columns if b in buses_red]
    loads_wide.columns = [f"load_{b}" for b in loads_wide.columns]
    cols_validas = [c for c in load_names if c in loads_wide.columns]
    n.loads_t.p_set = loads_wide[cols_validas]

    dem_max = loads_wide[cols_validas].sum(axis=1).max()
    print(f"  Buses con demanda : {n_cargas}")
    print(f"  Demanda maxima    : {dem_max:,.1f} MW")

    # Load shedding
    print(f"  Agregando load shedding virtual ({LOAD_SHED_COST:,.0f} USD/MWh) ...")
    for bus in n.buses.index:
        n.add("Generator", f"loadshed_{bus}",
              bus=bus, p_nom=LOAD_SHED_PNOM,
              carrier="load_shedding", marginal_cost=LOAD_SHED_COST)


# =============================================================================
# PASO 6 — Correr optimizacion
# =============================================================================

def correr_optimizacion(n, snapshots):
    print(f"\n[6/6] Corriendo optimizacion DC ...")
    print(f"  Solver    : HiGHS")
    print(f"  Snapshots : {len(snapshots)} horas")
    print(f"  Chunk dias: {CHUNK_DIAS if CHUNK_DIAS else 'sin chunk'}")

    if CHUNK_DIAS is None:
        return _correr_chunk(n, snapshots)
    else:
        return _correr_con_chunks(n, snapshots)


def _correr_chunk(n, snapshots_chunk):
    n.set_snapshots(snapshots_chunk)

    if not n.generators_t.p_max_pu.empty:
        n.generators_t.p_max_pu = n.generators_t.p_max_pu.reindex(snapshots_chunk).fillna(0.0)
    if not n.loads_t.p_set.empty:
        n.loads_t.p_set = n.loads_t.p_set.reindex(snapshots_chunk).fillna(0.0)

    resultado = n.optimize(solver_name="highs")
    status    = n.optimization_status if hasattr(n, "optimization_status") else resultado

    if not solver_status_ok(status):
        print(f"\n  [ERROR] Solver: {status}")
        print(f"  Posibles causas: congestion severa o generacion insuficiente.")
        return None

    return n


def _correr_con_chunks(n, snapshots_totales):
    p_max_pu_full = n.generators_t.p_max_pu.copy() if not n.generators_t.p_max_pu.empty else pd.DataFrame()
    p_set_full    = n.loads_t.p_set.copy()          if not n.loads_t.p_set.empty         else pd.DataFrame()

    chunks = []
    delta  = pd.Timedelta(days=CHUNK_DIAS)
    t      = snapshots_totales[0]
    fin    = snapshots_totales[-1]
    while t <= fin:
        t_fin = min(t + delta - pd.Timedelta(hours=1), fin)
        chunk = snapshots_totales[(snapshots_totales >= t) & (snapshots_totales <= t_fin)]
        if len(chunk) > 0:
            chunks.append(chunk)
        t += delta

    print(f"  Total de chunks: {len(chunks)}")
    acc_gen_p    = []
    acc_lines_p0 = []
    acc_links_p0 = []

    for i, chunk in enumerate(chunks, 1):
        print(f"\n  Chunk {i}/{len(chunks)}: {chunk[0].date()} -> {chunk[-1].date()} ({len(chunk)} h)")

        if not p_max_pu_full.empty:
            n.generators_t.p_max_pu = p_max_pu_full.reindex(chunk).fillna(0.0)
        if not p_set_full.empty:
            n.loads_t.p_set = p_set_full.reindex(chunk).fillna(0.0)

        n.set_snapshots(chunk)
        resultado = n.optimize(solver_name="highs")
        status    = n.optimization_status if hasattr(n, "optimization_status") else resultado

        if not solver_status_ok(status):
            print(f"    [ERROR] Chunk {i}: {status}. Se aborta.")
            return None

        acc_gen_p.append(n.generators_t.p.copy())
        acc_lines_p0.append(n.lines_t.p0.copy())
        if not n.links_t.p0.empty:
            acc_links_p0.append(n.links_t.p0.copy())

        print(f"    OK — generacion promedio: {n.generators_t.p.sum(axis=1).mean():,.1f} MW")

    print(f"\n  Concatenando {len(chunks)} chunks ...")
    n.set_snapshots(snapshots_totales)
    n.generators_t.p = pd.concat(acc_gen_p)
    n.lines_t.p0     = pd.concat(acc_lines_p0)
    if acc_links_p0:
        n.links_t.p0 = pd.concat(acc_links_p0)

    n.generators_t.p_max_pu = p_max_pu_full
    n.loads_t.p_set         = p_set_full
    return n


# =============================================================================
# GUARDAR Y REPORTAR
# =============================================================================

def guardar_resultados(n):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = nombre_output(FECHA_INICIO, FECHA_FIN)
    n.export_to_netcdf(output_file)
    print(f"\n  Guardado: {output_file}")
    return output_file


def reportar_load_shedding(n):
    print(f"\n{'='*60}")
    print(f"REPORTE DE LOAD SHEDDING")
    print(f"{'='*60}")

    gen_p         = n.generators_t.p
    loadshed_cols = [c for c in gen_p.columns if c.startswith("loadshed_")]

    if not loadshed_cols:
        print("  Sin columnas de load shedding en los resultados.")
        return

    ls_total = gen_p[loadshed_cols].sum(axis=1)
    ls_sum   = ls_total.sum()

    if ls_sum < 0.01:
        print("  Sin load shedding activado.")
    else:
        horas_con_ls = (ls_total > 0.01).sum()
        print(f"  [AVISO] Load shedding activado:")
        print(f"    Total acumulado : {ls_sum:,.1f} MWh")
        print(f"    Horas afectadas : {horas_con_ls} de {len(ls_total)}")
        print(f"    Hora pico       : {ls_total.idxmax()}  ({ls_total.max():,.1f} MW)")

        ls_por_bus = gen_p[loadshed_cols].sum().sort_values(ascending=False)
        ls_por_bus.index = ls_por_bus.index.str.replace("loadshed_", "", regex=False)
        print(f"\n  Top 5 buses con mayor load shedding:")
        for bus, mwh in ls_por_bus.head(5).items():
            if mwh > 0.01:
                print(f"    {bus:<30}  {mwh:>10,.1f} MWh")


def reportar_resumen(n):
    print(f"\n{'='*60}")
    print(f"RESUMEN DE LA CORRIDA")
    print(f"{'='*60}")

    gen_p       = n.generators_t.p
    gens_reales = [c for c in gen_p.columns if not c.startswith("loadshed_")]
    gen_real    = gen_p[gens_reales]

    gen_total_mwh = gen_real.sum().sum()
    print(f"\n  Generacion total: {gen_total_mwh:,.0f} MWh")

    # Agrupar carriers para el reporte
    carriers_raw = n.generators.loc[gens_reales, "carrier"]
    carriers_agrupados = carriers_raw.map(
        lambda c: "termica" if c in CARRIERS_TERMICA else
                  "hydro"   if c in CARRIERS_HYDRO   else c
    )

    mix = gen_real.sum().groupby(carriers_agrupados).sum().sort_values(ascending=False)
    print(f"\n  Mix de generacion por tecnologia:")
    for carrier, mwh in mix.items():
        pct = 100 * mwh / gen_total_mwh if gen_total_mwh > 0 else 0
        print(f"    {carrier:<20}: {mwh:>12,.0f} MWh  ({pct:>5.1f}%)")

    # Top 10 lineas mas cargadas
    if not n.lines_t.p0.empty and not n.lines["s_nom"].eq(0).all():
        p0_abs = n.lines_t.p0.abs()
        s_nom  = n.lines["s_nom"].replace(0, np.nan)
        util   = (p0_abs / s_nom * 100).mean().dropna().sort_values(ascending=False)
        print(f"\n  Top 10 lineas mas cargadas (% utilizacion promedio):")
        print(f"    {'Linea':<35} {'Util. promedio':>15}")
        for linea, pct in util.head(10).items():
            print(f"    {linea:<35} {pct:>14.1f}%")

    # Importacion Brasil
    if BRASIL_LINK in n.links_t.p0.columns:
        importacion_mwh = n.links_t.p0[BRASIL_LINK].clip(lower=0).sum()
        print(f"\n  Importacion acumulada de Brasil: {importacion_mwh:,.0f} MWh")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("19b_run_optimization_b.py -- despacho economico DC 2024b")
    print("=" * 60)
    print(f"\nPeriodo   : {FECHA_INICIO}  ->  {FECHA_FIN}")
    print(f"Chunk dias: {CHUNK_DIAS if CHUNK_DIAS else 'sin chunk'}")
    print(f"Sin costo : {'excluir' if EXCLUIR_SIN_COSTO else 'costo=0'}")

    print("\n[0/6] Verificando inputs ...")
    verificar_inputs()

    n         = cargar_network()
    snapshots = preparar_snapshots()
    agregar_generadores(n, snapshots)
    agregar_perfiles(n, snapshots)
    agregar_demanda(n, snapshots)

    n = correr_optimizacion(n, snapshots)

    if n is None:
        print("\n[ABORTADO] La optimizacion no convergio.")
        sys.exit(1)

    output_file = guardar_resultados(n)
    reportar_load_shedding(n)
    reportar_resumen(n)

    print(f"\n{'='*60}")
    print(f"Corrida completada.")
    print(f"Output: {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
