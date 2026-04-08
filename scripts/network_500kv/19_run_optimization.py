"""
19_run_optimization.py
Corre el despacho economico lineal DC (OPF) sobre la red 500 kV argentina
para el periodo configurado. Usa n.optimize() de PyPSA con solver HiGHS.

Inputs (versionados en GitHub):
    networks/network_500kv.nc
    data/network_500kv/generators_2024.csv
    data/network_500kv/loads_2024.csv
    data/network_500kv/costos_marginales_2024.csv

Inputs (externos a GitHub):
    Official data/gen_profiles_2024.csv

Output:
    networks/results_2024_YYYYMMDD_YYYYMMDD.nc
        El sufijo de fechas evita pisar corridas anteriores.
        El archivo NO se versiona en GitHub (carpeta en .gitignore).

Logica general:
    1. Carga network_500kv.nc (red: buses, lineas, trafos, link Brasil).
    2. Agrega los 626 generadores dinamicamente con p_nom y costo marginal.
       Generadores sin costo en costos_marginales_2024.csv reciben costo=0
       salvo que EXCLUIR_SIN_COSTO=True, en cuyo caso se omiten del modelo.
    3. Asigna perfiles horarios de disponibilidad (p_max_pu) desde
       gen_profiles_2024.csv para cada generador y cada snapshot.
    4. Asigna demanda horaria (p_set) a los 72 buses con datos en loads_2024.csv.
       Buses sin datos en ese archivo quedan con demanda=0.
    5. Agrega load shedding virtual en cada bus (costo muy alto) para garantizar
       que el problema siempre tenga solucion matematica.
    6. Corre n.optimize() con HiGHS. Si CHUNK_DIAS esta definido, resuelve
       el periodo en bloques para reducir el uso de memoria RAM.
    7. Verifica el estado del solver. Si es infeasible, avisa y no guarda.
    8. Guarda resultados en .nc y emite reporte de load shedding activado.

Decisiones de modelado:
    - DC OPF lineal: sin perdidas, sin tensiones, solo flujos activos.
    - Sin restricciones adicionales: no hay minimos tecnicos ni rampas.
    - Slack bus: ATUCHA 2_21kV (bus de maquina nuclear, estable y central).
    - Link Brasil: solo importacion (p_min=0), libre para el solver.
    - Load shedding: LOAD_SHED_COST USD/MWh, p_nom ilimitado por bus.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/19_run_optimization.py
"""

import os
import sys
import pandas as pd
import numpy as np
import pypsa

# =============================================================================
# CONFIGURACION — modificar segun la corrida deseada
# =============================================================================

# --- Rutas de inputs ---
NETWORK_FILE  = "/mnt/c/Work/pypsa-ar-base/networks/network_500kv.nc"
GEN_FILE      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_2024.csv"
LOADS_FILE    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/loads_2024.csv"
COSTOS_FILE   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/costos_marginales_2024.csv"
PROFILES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/gen_profiles_2024.csv"  # externo a GitHub

# --- Ruta de output ---
OUTPUT_DIR    = "/mnt/c/Work/pypsa-ar-base/networks"

# --- Periodo de simulacion ---
# Para una prueba rapida: FECHA_FIN = "2024-01-01" (un solo dia = 24 snapshots)
# Para el pico de demanda: FECHA_INICIO = FECHA_FIN = "2024-02-01"
# Para el año completo:    FECHA_FIN = "2024-12-31"
FECHA_INICIO  = "2024-02-01"
FECHA_FIN     = "2024-02-07"

# --- Chunking ---
# None  : resuelve todo el periodo en un solo problema (mas rapido pero mas RAM)
# 1     : resuelve dia a dia
# 7     : resuelve semana a semana (recomendado para periodos largos)
# 30    : resuelve mes a mes
CHUNK_DIAS    = None

# --- Generadores sin costo marginal ---
# False : se les asigna costo_marginal = 0 (comportamiento por defecto)
# True  : se excluyen del modelo (no generan)
EXCLUIR_SIN_COSTO = False

# --- Parametros de load shedding ---
# Generador virtual en cada bus para garantizar factibilidad del problema.
# El costo alto lo hace indeseable para el solver salvo que no haya alternativa.
LOAD_SHED_COST  = 10_000.0   # USD/MWh
LOAD_SHED_PNOM  = 99_999.0   # MW por bus (efectivamente ilimitado)

# --- Bus de referencia angular (slack) ---
SLACK_BUS = "ATUCHA 2_21kV"

# --- Nombre del Link de importacion Brasil en el network ---
BRASIL_LINK = "importacion_brasil"

# --- Buses aislados conocidos a excluir del OPF ---
# Se excluyen explicitamente del script 19 porque aparecen en el network base
# pero no forman parte de la red principal abastecible en la optimizacion.
# BRASIL no se toca: queda como bus fuente del Link internacional.
BUSES_A_EXCLUIR_OPF = {"T PEPE", "PBUENA2", "PBUENA2_20kV"}


# =============================================================================
# HELPERS
# =============================================================================

def verificar_inputs():
    """Verifica que todos los archivos de input existen antes de arrancar."""
    archivos = {
        "network_500kv.nc"          : NETWORK_FILE,
        "generators_2024.csv"       : GEN_FILE,
        "loads_2024.csv"            : LOADS_FILE,
        "costos_marginales_2024.csv": COSTOS_FILE,
        "gen_profiles_2024.csv"     : PROFILES_FILE,
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
    """Construye el nombre del archivo de output con sufijo de fechas."""
    ini = pd.Timestamp(fecha_ini).strftime("%Y%m%d")
    fin = pd.Timestamp(fecha_fin).strftime("%Y%m%d")
    return os.path.join(OUTPUT_DIR, f"results_2024_{ini}_{fin}.nc")


def parsear_snapshots_csv(serie):
    """
    Parsea una columna datetime del formato DD/MM/YYYY HH:MM
    al DatetimeIndex estandar de PyPSA.
    """
    return pd.to_datetime(serie, dayfirst=True, format="%d/%m/%Y %H:%M")

def solver_status_ok(status):
    """
    Interpreta de forma robusta el estado devuelto por PyPSA/Linopy/solver.

    Casos esperables segun version:
        "ok"
        "optimal"
        ("ok", "optimal")
        ["ok", "optimal"]

    Retorna True si la optimizacion fue exitosa.
    """
    if status is None:
        return False

    if isinstance(status, str):
        return status.strip().lower() in {"ok", "optimal"}

    if isinstance(status, (tuple, list)):
        status_norm = tuple(str(x).strip().lower() for x in status)
        return status_norm in {
            ("ok",),
            ("optimal",),
            ("ok", "optimal"),
            ("optimal", "ok"),
        }

    return str(status).strip().lower() in {"ok", "optimal"}




# =============================================================================
# PASO 1 — Cargar network base
# =============================================================================

def cargar_network():
    """
    Carga network_500kv.nc y configura el slack bus y el Link de Brasil.
    El network contiene solo la red (buses, lineas, trafos, link Brasil).
    Generadores y cargas se agregan dinamicamente en pasos siguientes.
    """
    print("\n[1/7] Cargando network base ...")
    n = pypsa.Network(NETWORK_FILE)
    print(f"  Buses        : {len(n.buses)}")
    print(f"  Lineas       : {len(n.lines)}")
    print(f"  Transformadores: {len(n.transformers)}")
    print(f"  Links        : {len(n.links)}")

    # --- Slack bus ---
    if SLACK_BUS in n.buses.index:
        n.buses.loc[SLACK_BUS, "control"] = "Slack"
        print(f"  Slack bus    : {SLACK_BUS}")
    else:
        print(f"  [AVISO] Slack bus '{SLACK_BUS}' no encontrado — PyPSA asignara automaticamente")

    # --- Link Brasil: solo importacion ---
    if BRASIL_LINK in n.links.index:
        n.links.loc[BRASIL_LINK, "p_min_pu"] = 0.0
        print(f"  Link Brasil  : p_min_pu=0 (solo importacion)")
    else:
        print(f"  [AVISO] Link '{BRASIL_LINK}' no encontrado en el network")

    # --- Excluir buses aislados conocidos que no deben entrar al OPF ---
    excluir_buses_aislados_opf(n)

    print(f"  Buses finales : {len(n.buses)}")
    print(f"  Lineas finales: {len(n.lines)}")
    print(f"  Trafos finales: {len(n.transformers)}")
    print(f"  Links finales : {len(n.links)}")

    return n

def excluir_buses_aislados_opf(n):
    """
    Excluye del network buses aislados conocidos que no deben participar
    de la optimizacion 2024.

    Se eliminan:
        - los buses indicados en BUSES_A_EXCLUIR_OPF
        - lineas conectadas a esos buses
        - transformadores conectados a esos buses
        - links conectados a esos buses (si existieran)

    No toca BRASIL ni aplica una purga general por subredes.
    """
    buses_presentes = [b for b in BUSES_A_EXCLUIR_OPF if b in n.buses.index]

    if not buses_presentes:
        print("  Sin buses aislados conocidos para excluir del OPF.")
        return

    print(f"  Excluyendo buses aislados conocidos del OPF: {sorted(buses_presentes)}")

    lineas_drop = n.lines[
        n.lines["bus0"].isin(buses_presentes) |
        n.lines["bus1"].isin(buses_presentes)
    ].index.tolist()

    trafos_drop = n.transformers[
        n.transformers["bus0"].isin(buses_presentes) |
        n.transformers["bus1"].isin(buses_presentes)
    ].index.tolist()

    links_drop = n.links[
        n.links["bus0"].isin(buses_presentes) |
        n.links["bus1"].isin(buses_presentes)
    ].index.tolist()

    for name in lineas_drop:
        n.remove("Line", name)

    for name in trafos_drop:
        n.remove("Transformer", name)

    for name in links_drop:
        n.remove("Link", name)

    for bus in buses_presentes:
        n.remove("Bus", bus)

    print(f"    Buses removidos  : {len(buses_presentes)}")
    print(f"    Lineas removidas : {len(lineas_drop)}")
    print(f"    Trafos removidos : {len(trafos_drop)}")
    print(f"    Links removidos  : {len(links_drop)}")
# =============================================================================
# PASO 2 — Preparar snapshots del periodo configurado
# =============================================================================

def preparar_snapshots():
    """
    Construye el DatetimeIndex horario para el periodo FECHA_INICIO / FECHA_FIN.
    2024 es bisiesto: 8784 horas.
    """
    print(f"\n[2/7] Preparando snapshots ...")
    snapshots = pd.date_range(
        start = FECHA_INICIO,
        end   = pd.Timestamp(FECHA_FIN) + pd.Timedelta(hours=23),
        freq  = "h",
    )
    print(f"  Periodo  : {FECHA_INICIO}  ->  {FECHA_FIN}")
    print(f"  Snapshots: {len(snapshots)} horas")
    return snapshots


# =============================================================================
# PASO 3 — Agregar generadores con p_nom y costo marginal
# =============================================================================

def agregar_generadores(n, snapshots):
    """
    Lee generators_2024.csv y costos_marginales_2024.csv, hace join por gen_key,
    y agrega cada unidad al network con:
        bus      = bus_conexion500kv_name
        p_nom    = p_nom de generators_2024
        carrier  = carrier
        marginal_cost = costo_marginal de costos_marginales_2024
                        0 si no hay costo y EXCLUIR_SIN_COSTO=False
                        unidad excluida si EXCLUIR_SIN_COSTO=True

    Retorna el DataFrame de generadores efectivamente agregados al network.
    """
    print(f"\n[3/7] Agregando generadores ...")

    gen  = pd.read_csv(GEN_FILE)
    cost = pd.read_csv(COSTOS_FILE)[["gen_key", "costo_marginal(USD/mwh)"]].copy()
    cost.rename(columns={"costo_marginal(USD/mwh)": "costo_marginal"}, inplace=True)

    gen = gen.merge(cost, on="gen_key", how="left")

    # Generadores sin costo
    sin_costo = gen["costo_marginal"].isna()
    n_sin_costo = sin_costo.sum()

    if EXCLUIR_SIN_COSTO:
        gen = gen[~sin_costo].copy()
        print(f"  [INFO] {n_sin_costo} generadores sin costo excluidos (EXCLUIR_SIN_COSTO=True)")
    else:
        gen.loc[sin_costo, "costo_marginal"] = 0.0
        print(f"  [INFO] {n_sin_costo} generadores sin costo -> costo_marginal=0")

    buses_red = set(n.buses.index)
    n_agregados   = 0
    n_bus_faltante = 0

    for _, row in gen.iterrows():
        bus = row.get("bus_conexion500kv_name")
        if pd.isna(bus) or bus not in buses_red:
            n_bus_faltante += 1
            continue

        n.add(
            "Generator",
            row["gen_key"],
            bus           = bus,
            p_nom         = float(row["p_nom"]),
            carrier       = row["carrier"],
            marginal_cost = float(row["costo_marginal"]),
        )
        n_agregados += 1

    print(f"  Generadores agregados  : {n_agregados}")
    if n_bus_faltante:
        print(f"  [AVISO] {n_bus_faltante} generadores omitidos — bus de conexion no encontrado en el network")

    gen_en_red = gen[gen["bus_conexion500kv_name"].isin(buses_red)].copy()
    return gen_en_red


# =============================================================================
# PASO 4 — Agregar perfiles horarios de disponibilidad (p_max_pu)
# =============================================================================

def agregar_perfiles(n, snapshots):
    """
    Lee gen_profiles_2024.csv (archivo externo a GitHub, ~5.3M filas),
    filtra al periodo de interes, pivota a formato ancho y asigna como
    n.generators_t.p_max_pu.

    Formato del CSV: gen_key, bus_conexion500kv_name, carrier, datetime, p_max_pu
    Formato datetime en el CSV: DD/MM/YYYY HH:MM
    """
    print(f"\n[4/7] Cargando perfiles de disponibilidad (gen_profiles_2024.csv) ...")
    print(f"  Archivo externo a GitHub: {PROFILES_FILE}")

    # Leer en chunks para no cargar los 5.3M filas de golpe en memoria
    chunks      = []
    chunk_size  = 500_000
    ts_inicio   = snapshots[0]
    ts_fin      = snapshots[-1]

    for chunk in pd.read_csv(PROFILES_FILE, chunksize=chunk_size, low_memory=False):
        chunk["ts"] = parsear_snapshots_csv(chunk["datetime"])
        chunk = chunk[(chunk["ts"] >= ts_inicio) & (chunk["ts"] <= ts_fin)]
        if not chunk.empty:
            chunks.append(chunk[["gen_key", "ts", "p_max_pu"]])

    if not chunks:
        print("  [ERROR] No se encontraron filas de perfiles para el periodo configurado.")
        sys.exit(1)

    perfiles = pd.concat(chunks, ignore_index=True)

    # Pivotear: filas=timestamp, columnas=gen_key
    perfiles_wide = perfiles.pivot_table(
        index   = "ts",
        columns = "gen_key",
        values  = "p_max_pu",
        aggfunc = "first",
    )
    perfiles_wide.index.name = None

    # Alinear al DatetimeIndex del periodo
    perfiles_wide = perfiles_wide.reindex(snapshots)

    # Rellenar NaN con 0 (sin disponibilidad en esa hora)
    perfiles_wide = perfiles_wide.fillna(0.0)

    # Solo incluir columnas que corresponden a generadores en el network
    gens_en_red = set(n.generators.index)
    cols_validas = [c for c in perfiles_wide.columns if c in gens_en_red]
    perfiles_wide = perfiles_wide[cols_validas]

    n.generators_t.p_max_pu = perfiles_wide

    print(f"  Generadores con perfil : {len(cols_validas)}")
    print(f"  Snapshots cubiertos    : {len(perfiles_wide)}")

    # Excluir del network los generadores sin perfil en gen_profiles_2024.csv
    gens_sin_perfil = gens_en_red - set(cols_validas)
    if gens_sin_perfil:
        for gen_name in sorted(gens_sin_perfil):
            n.remove("Generator", gen_name)
        print(f"  {len(gens_sin_perfil)} generadores sin perfil excluidos del network (fuera del MEM)")

# =============================================================================
# PASO 5 — Agregar demanda horaria por bus
# =============================================================================

def agregar_demanda(n, snapshots):
    """
    Lee loads_2024.csv, filtra al periodo, pivota a formato ancho
    y agrega una Load por bus con su perfil horario como p_set.

    Buses sin datos en loads_2024.csv quedan con demanda=0.
    Formato datetime en el CSV: DD/MM/YYYY HH:MM
    """
    print(f"\n[5/7] Cargando demanda horaria (loads_2024.csv) ...")

    loads = pd.read_csv(LOADS_FILE)
    loads["ts"] = parsear_snapshots_csv(loads["datetime"])

    ts_inicio = snapshots[0]
    ts_fin    = snapshots[-1]
    loads = loads[(loads["ts"] >= ts_inicio) & (loads["ts"] <= ts_fin)].copy()

    # Pivotear: filas=timestamp, columnas=bus_name
    loads_wide = loads.pivot_table(
        index   = "ts",
        columns = "bus_name",
        values  = "p_mw",
        aggfunc = "sum",
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

    # Asignar perfiles de demanda
    load_names    = [f"load_{b}" for b in loads_wide.columns if b in buses_red]
    loads_wide.columns = [f"load_{b}" for b in loads_wide.columns]
    cols_validas  = [c for c in load_names if c in loads_wide.columns]
    n.loads_t.p_set = loads_wide[cols_validas]

    dem_max = loads_wide[cols_validas].sum(axis=1).max()
    print(f"  Buses con demanda : {n_cargas}")
    print(f"  Demanda maxima    : {dem_max:,.1f} MW  (en el periodo configurado)")


# =============================================================================
# PASO 6 — Agregar load shedding virtual
# =============================================================================

def agregar_load_shedding(n):
    """
    Agrega un generador virtual de load shedding en cada bus del network.
    Costo muy alto (LOAD_SHED_COST) lo hace indeseable pero garantiza
    que el problema OPF siempre tenga solucion.

    Nombre de cada generador: 'loadshed_{bus_name}'
    Carrier: 'load_shedding'
    """
    print(f"\n[6/7] Agregando load shedding virtual ...")

    n_loadshed = 0
    for bus in n.buses.index:
        n.add(
            "Generator",
            f"loadshed_{bus}",
            bus           = bus,
            p_nom         = LOAD_SHED_PNOM,
            carrier       = "load_shedding",
            marginal_cost = LOAD_SHED_COST,
        )
        n_loadshed += 1

    print(f"  Load shedders agregados: {n_loadshed} (uno por bus)")
    print(f"  Costo load shedding    : {LOAD_SHED_COST:,.0f} USD/MWh")


# =============================================================================
# PASO 7 — Correr optimizacion
# =============================================================================

def correr_optimizacion(n, snapshots):
    """
    Corre n.optimize() con HiGHS sobre el periodo configurado.

    Si CHUNK_DIAS es None: resuelve todo el periodo en un problema unico.
    Si CHUNK_DIAS es un numero: divide los snapshots en bloques de ese
    tamaño en dias, resuelve cada bloque por separado y concatena los
    resultados en memoria antes de exportar.

    En caso de infeasible: avisa en consola y retorna None.
    Retorna el network con los resultados cargados, o None si fallo.
    """
    print(f"\n[7/7] Corriendo optimizacion DC ...")
    print(f"  Solver     : HiGHS")
    print(f"  Snapshots  : {len(snapshots)} horas")
    print(f"  Chunk dias : {CHUNK_DIAS if CHUNK_DIAS else 'sin chunk (problema unico)'}")

    if CHUNK_DIAS is None:
        return _correr_chunk(n, snapshots)
    else:
        return _correr_con_chunks(n, snapshots)


def _correr_chunk(n, snapshots_chunk):
    """
    Resuelve un unico problema de optimizacion para los snapshots dados.
    Retorna el network con resultados, o None si el solver falla.
    """
    n.set_snapshots(snapshots_chunk)

    # Filtrar p_max_pu y p_set al chunk actual
    if not n.generators_t.p_max_pu.empty:
        n.generators_t.p_max_pu = n.generators_t.p_max_pu.reindex(snapshots_chunk)
    if not n.loads_t.p_set.empty:
        n.loads_t.p_set = n.loads_t.p_set.reindex(snapshots_chunk).fillna(0.0)

    resultado = n.optimize(solver_name="highs")

    status = n.optimization_status if hasattr(n, "optimization_status") else resultado

    if not solver_status_ok(status):
        print(f"\n  [ERROR] Solver retorno estado: {status}")
        print(f"          No se guarda el archivo de resultados.")
        print(f"          Posibles causas:")
        print(f"            - Congestion severa en la red 500 kV")
        print(f"            - Generacion insuficiente para la demanda en alguna hora")
        print(f"            - Revisar perfiles p_max_pu y demanda en el periodo")
        return None

    return n


def _correr_con_chunks(n, snapshots_totales):
    """
    Divide los snapshots en bloques de CHUNK_DIAS dias, resuelve cada uno
    y acumula los resultados en DataFrames. Al finalizar, reconstruye el
    network con todos los resultados para exportar.
    """
    # Guardar versiones completas de los inputs para restaurar en cada chunk
    p_max_pu_full = n.generators_t.p_max_pu.copy() if not n.generators_t.p_max_pu.empty else pd.DataFrame()
    p_set_full    = n.loads_t.p_set.copy()          if not n.loads_t.p_set.empty         else pd.DataFrame()

    # Construir lista de chunks
    chunks = []
    delta  = pd.Timedelta(days=CHUNK_DIAS)
    inicio = snapshots_totales[0]
    fin    = snapshots_totales[-1]

    t = inicio
    while t <= fin:
        t_fin_chunk = min(t + delta - pd.Timedelta(hours=1), fin)
        chunk = snapshots_totales[(snapshots_totales >= t) & (snapshots_totales <= t_fin_chunk)]
        if len(chunk) > 0:
            chunks.append(chunk)
        t += delta

    print(f"  Total de chunks: {len(chunks)}")

    # Acumuladores de resultados
    acc_gen_p       = []
    acc_lines_p0    = []
    acc_links_p0    = []

    for i, chunk in enumerate(chunks, 1):
        print(f"\n  Chunk {i}/{len(chunks)}: {chunk[0].date()}  ->  {chunk[-1].date()}  ({len(chunk)} h)")

        # Restaurar inputs completos y filtrar al chunk
        if not p_max_pu_full.empty:
            n.generators_t.p_max_pu = p_max_pu_full.reindex(chunk)
        if not p_set_full.empty:
            n.loads_t.p_set = p_set_full.reindex(chunk).fillna(0.0)

        n.set_snapshots(chunk)
       
        resultado = n.optimize(solver_name="highs")
        status    = n.optimization_status if hasattr(n, "optimization_status") else resultado

        if not solver_status_ok(status):
            print(f"    [ERROR] Chunk {i} infeasible — estado: {status}. Se aborta.")
            return None

        acc_gen_p.append(n.generators_t.p.copy())
        acc_lines_p0.append(n.lines_t.p0.copy())
        if not n.links_t.p0.empty:
            acc_links_p0.append(n.links_t.p0.copy())

        print(f"    OK — generacion total: {n.generators_t.p.sum(axis=1).mean():,.1f} MW promedio")

    # Reconstruir network con todos los resultados
    print(f"\n  Concatenando resultados de {len(chunks)} chunks ...")
    n.set_snapshots(snapshots_totales)
    n.generators_t.p  = pd.concat(acc_gen_p)
    n.lines_t.p0      = pd.concat(acc_lines_p0)
    if acc_links_p0:
        n.links_t.p0  = pd.concat(acc_links_p0)

    # Restaurar inputs completos al network final
    n.generators_t.p_max_pu = p_max_pu_full
    n.loads_t.p_set         = p_set_full

    return n


# =============================================================================
# GUARDAR Y REPORTAR
# =============================================================================

def guardar_resultados(n):
    """Exporta el network con resultados a .nc."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = nombre_output(FECHA_INICIO, FECHA_FIN)
    n.export_to_netcdf(output_file)
    print(f"\n  Guardado: {output_file}")
    return output_file


def reportar_load_shedding(n):
    """
    Muestra cuanto load shedding se activo, por hora y por bus.
    Si no hubo load shedding, confirma que el sistema resolvio sin problemas.
    """
    print(f"\n{'='*60}")
    print(f"REPORTE DE LOAD SHEDDING")
    print(f"{'='*60}")

    gen_p = n.generators_t.p
    loadshed_cols = [c for c in gen_p.columns if c.startswith("loadshed_")]

    if not loadshed_cols:
        print("  No se encontraron columnas de load shedding en los resultados.")
        return

    ls_total = gen_p[loadshed_cols].sum(axis=1)
    ls_sum   = ls_total.sum()

    if ls_sum < 0.01:
        print("  Sin load shedding activado. El sistema resolvio sin necesidad de generacion virtual.")
    else:
        horas_con_ls = (ls_total > 0.01).sum()
        print(f"  [AVISO] Load shedding activado:")
        print(f"    Total acumulado : {ls_sum:,.1f} MWh")
        print(f"    Horas afectadas : {horas_con_ls} de {len(ls_total)}")
        print(f"    Hora pico       : {ls_total.idxmax()}  ({ls_total.max():,.1f} MW)")

        # Top 5 buses con mas load shedding
        ls_por_bus = gen_p[loadshed_cols].sum().sort_values(ascending=False)
        ls_por_bus.index = ls_por_bus.index.str.replace("loadshed_", "", regex=False)
        print(f"\n  Top 5 buses con mayor load shedding:")
        for bus, mwh in ls_por_bus.head(5).items():
            if mwh > 0.01:
                print(f"    {bus:<30}  {mwh:>10,.1f} MWh")


def reportar_resumen(n):
    """Reporte final de la corrida: generacion total, mix, lineas congestionadas."""
    print(f"\n{'='*60}")
    print(f"RESUMEN DE LA CORRIDA")
    print(f"{'='*60}")

    gen_p = n.generators_t.p

    # Excluir load shedding del mix real
    gens_reales = [c for c in gen_p.columns if not c.startswith("loadshed_")]
    gen_real    = gen_p[gens_reales]

    gen_total_mwh = gen_real.sum().sum()
    print(f"\n  Generacion total: {gen_total_mwh:,.0f} MWh")

    # Mix por carrier
    carriers = n.generators.loc[gens_reales, "carrier"]
    mix = gen_real.sum().groupby(carriers).sum().sort_values(ascending=False)
    print(f"\n  Mix de generacion por tecnologia:")
    for carrier, mwh in mix.items():
        pct = 100 * mwh / gen_total_mwh if gen_total_mwh > 0 else 0
        print(f"    {carrier:<20}: {mwh:>12,.0f} MWh  ({pct:>5.1f}%)")

    # Lineas mas cargadas (promedio de utilizacion)
    if not n.lines_t.p0.empty and not n.lines["s_nom"].eq(0).all():
        p0_abs  = n.lines_t.p0.abs()
        s_nom   = n.lines["s_nom"].replace(0, np.nan)
        util    = (p0_abs / s_nom * 100).mean().dropna().sort_values(ascending=False)
        print(f"\n  Top 10 lineas mas cargadas (% utilizacion promedio):")
        print(f"    {'Linea':<35} {'Util. promedio':>15}")
        for linea, pct in util.head(10).items():
            print(f"    {linea:<35} {pct:>14.1f}%")

    # Link Brasil
    if BRASIL_LINK in n.links_t.p0.columns:
        importacion_mwh = n.links_t.p0[BRASIL_LINK].clip(lower=0).sum()
        print(f"\n  Importacion acumulada de Brasil: {importacion_mwh:,.0f} MWh")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("19_run_optimization.py -- despacho economico DC 2024")
    print("=" * 60)
    print(f"\nPeriodo   : {FECHA_INICIO}  ->  {FECHA_FIN}")
    print(f"Chunk dias: {CHUNK_DIAS if CHUNK_DIAS else 'sin chunk'}")
    print(f"Sin costo : {'excluir' if EXCLUIR_SIN_COSTO else 'costo=0'}")

    # Verificar inputs
    print("\n[0/7] Verificando inputs ...")
    verificar_inputs()

    # Pipeline
    n         = cargar_network()
    snapshots = preparar_snapshots()
    gen_df    = agregar_generadores(n, snapshots)
    agregar_perfiles(n, snapshots)
    agregar_demanda(n, snapshots)
    agregar_load_shedding(n)

    n = correr_optimizacion(n, snapshots)

    if n is None:
        print("\n[ABORTADO] La optimizacion no convergio. No se genero archivo de resultados.")
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
