"""
21_network_clustering.py
Genera versiones simplificadas de la red 500 kV mediante clustering espacial
k-means nativo de PyPSA. Para cada nivel de agregacion definido en
CLUSTER_SIZES produce un network clusterizado funcional para optimizacion
y los archivos de visualizacion correspondientes.

Inputs (versionados en GitHub):
    networks/network_500kv.nc
    data/network_500kv/generators_2024.csv
    data/network_500kv/loads_2024.csv
    data/network_500kv/costos_marginales_2024.csv

Inputs (externos a GitHub):
    Official data/gen_profiles_2024.csv

Outputs — todos en data/network_500kv/clusters/:
    clusters.gpkg
        Layer por cada N en CLUSTER_SIZES:
            k{N}_buses      : buses originales con cluster_id asignado
            k{N}_centroids  : super-buses (centroides de cada cluster)
            k{N}_lines      : lineas equivalentes entre clusters

    cluster_summary_k{N}.csv
        Una fila por cluster. Campos:
            cluster_id, centroid_lat, centroid_lon, n_buses,
            p_nom_hydro_mw        (hydro + pumped_hydro)
            p_nom_nuclear_mw
            p_nom_termica_mw      (ccgt + ocgt + steam + diesel)
            p_nom_wind_mw
            p_nom_solar_mw
            p_nom_bioenergia_mw   (biomass + biogas)
            p_nom_total_mw

    cluster_k{N}.nc
        Network PyPSA clusterizado con generadores, perfiles, demanda y
        costos cargados. Listo para n.optimize() sin pasos adicionales.

Logica:
    1. Carga network_500kv.nc y agrega generadores, costos, perfiles y demanda.
       El network debe tener todos los componentes para que get_clustering_from_busmap
       los agregue correctamente en los super-buses.
    2. Para cada N en CLUSTER_SIZES:
       a. Corre kmeans_clustering(n, N) -> obtiene busmap (bus -> cluster_id)
          y network clusterizado.
       b. Exporta network clusterizado a .nc.
       c. Construye GeoDataFrames de buses, centroides y lineas equivalentes
          y los escribe como layers en clusters.gpkg.
       d. Construye cluster_summary_k{N}.csv agrupando p_nom por tecnologia.

Notas de modelado:
    - El clustering usa coordenadas geograficas (x=lon, y=lat) de los buses.
    - Buses sin coordenadas se excluyen del calculo k-means pero se fusionan
      con el cluster mas cercano via get_clustering_from_busmap.
    - Los perfiles horarios (gen_profiles_2024.csv) se cargan completos para
      que el network clusterizado quede funcional para optimizacion futura.
    - La demanda se carga desde loads_2024.csv en formato largo.
    - Generadores sin costo marginal reciben costo_marginal = 0.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/21_network_clustering.py
"""

import os
import sys
import pandas as pd
import numpy as np
import pypsa
import geopandas as gpd
from shapely.geometry import Point, LineString
from pypsa.clustering.spatial import kmeans_clustering

# =============================================================================
# CONFIGURACION — modificar segun la corrida deseada
# =============================================================================

# Niveles de agregacion deseados. Agregar o quitar valores segun necesidad.
CLUSTER_SIZES = [10, 20, 50]

# Criterio de pesos para el clustering k-means
# "uniforme" : todos los buses pesan igual (clustering puramente geografico)
# "p_nom"    : buses con mas generacion pesan mas
# "demanda"  : buses con mas demanda pesan mas
BUS_WEIGHTING = "uniforme"

# --- Rutas de inputs ---
NETWORK_FILE  = "/mnt/c/Work/pypsa-ar-base/networks/network_500kv.nc"
GEN_FILE      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_2024.csv"
LOADS_FILE    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/loads_2024.csv"
COSTOS_FILE   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/costos_marginales_2024.csv"
PROFILES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/gen_profiles_2024.csv"  # externo a GitHub

# --- Ruta de outputs ---
OUTPUT_DIR    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/clusters"
GPKG_FILE     = os.path.join(OUTPUT_DIR, "clusters.gpkg")

# --- CRS geografico ---
CRS = "EPSG:4326"

# --- Generadores sin costo marginal ---
# False : se les asigna costo_marginal = 0
# True  : se excluyen del modelo
EXCLUIR_SIN_COSTO = False



# --- Agrupacion de carriers para el summary ---
CARRIERS_HYDRO      = {"hydro", "pumped_hydro"}
CARRIERS_NUCLEAR    = {"nuclear"}
CARRIERS_TERMICA    = {"ccgt", "ocgt", "steam", "diesel"}
CARRIERS_WIND       = {"wind"}
CARRIERS_SOLAR      = {"solar"}
CARRIERS_BIOENERGIA = {"biomass", "biogas"}


# =============================================================================
# HELPERS
# =============================================================================

def verificar_inputs():
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


def parsear_snapshots_csv(serie):
    return pd.to_datetime(serie, dayfirst=True, format="%d/%m/%Y %H:%M")


def agrupar_carrier(carrier):
    """Mapea carrier individual a categoria del summary."""
    if carrier in CARRIERS_HYDRO:
        return "hydro"
    if carrier in CARRIERS_NUCLEAR:
        return "nuclear"
    if carrier in CARRIERS_TERMICA:
        return "termica"
    if carrier in CARRIERS_WIND:
        return "wind"
    if carrier in CARRIERS_SOLAR:
        return "solar"
    if carrier in CARRIERS_BIOENERGIA:
        return "bioenergia"
    return "otros"


# =============================================================================
# PASO 1 — Cargar network base
# =============================================================================

def cargar_network():
    print("\n[1/6] Cargando network base ...")
    n = pypsa.Network(NETWORK_FILE)
    print(f"  Buses          : {len(n.buses)}")
    print(f"  Lineas         : {len(n.lines)}")
    print(f"  Transformadores: {len(n.transformers)}")
    return n


# =============================================================================
# PASO 2 — Agregar generadores con p_nom y costo marginal
# =============================================================================

def agregar_generadores(n):
    print(f"\n[2/6] Agregando generadores ...")

    gen  = pd.read_csv(GEN_FILE)
    cost = pd.read_csv(COSTOS_FILE)[["gen_key", "costo_marginal(USD/mwh)"]].copy()
    cost.rename(columns={"costo_marginal(USD/mwh)": "costo_marginal"}, inplace=True)

    gen = gen.merge(cost, on="gen_key", how="left")

    sin_costo  = gen["costo_marginal"].isna()
    n_sin_costo = sin_costo.sum()

    if EXCLUIR_SIN_COSTO:
        gen = gen[~sin_costo].copy()
        print(f"  [INFO] {n_sin_costo} generadores sin costo excluidos (EXCLUIR_SIN_COSTO=True)")
    else:
        gen.loc[sin_costo, "costo_marginal"] = 0.0
        print(f"  [INFO] {n_sin_costo} generadores sin costo -> costo_marginal=0")

    buses_red      = set(n.buses.index)
    n_agregados    = 0
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
        print(f"  [AVISO] {n_bus_faltante} generadores omitidos — bus no encontrado en el network")


# =============================================================================
# PASO 3 — Agregar perfiles horarios de disponibilidad (p_max_pu)
# =============================================================================

def agregar_perfiles(n):
    print(f"\n[3/6] Cargando perfiles de disponibilidad (gen_profiles_2024.csv) ...")
    print(f"  Archivo externo a GitHub: {PROFILES_FILE}")

    chunks     = []
    chunk_size = 500_000

    for chunk in pd.read_csv(PROFILES_FILE, chunksize=chunk_size, low_memory=False):
        chunk["ts"] = parsear_snapshots_csv(chunk["datetime"])
        chunks.append(chunk[["gen_key", "ts", "p_max_pu"]])

    perfiles = pd.concat(chunks, ignore_index=True)

    perfiles_wide = perfiles.pivot_table(
        index   = "ts",
        columns = "gen_key",
        values  = "p_max_pu",
        aggfunc = "first",
    )
    perfiles_wide.index.name = None
    perfiles_wide = perfiles_wide.fillna(0.0)

    gens_en_red  = set(n.generators.index)
    cols_validas = [c for c in perfiles_wide.columns if c in gens_en_red]
    perfiles_wide = perfiles_wide[cols_validas]

    n.generators_t.p_max_pu = perfiles_wide

    print(f"  Generadores con perfil : {len(cols_validas)}")
    print(f"  Snapshots cubiertos    : {len(perfiles_wide)}")

       # Excluir del network los generadores sin perfil en gen_profiles_2024.csv
    gens_sin_perfil = gens_en_red - set(cols_validas)
    if gens_sin_perfil:
        for gen_key in gens_sin_perfil:
            n.remove("Generator", gen_key)
       


# =============================================================================
# PASO 4 — Agregar demanda horaria por bus
# =============================================================================

def agregar_demanda(n):
    print(f"\n[4/6] Cargando demanda horaria (loads_2024.csv) ...")

    loads = pd.read_csv(LOADS_FILE)
    loads["ts"] = parsear_snapshots_csv(loads["datetime"])

    loads_wide = loads.pivot_table(
        index   = "ts",
        columns = "bus_name",
        values  = "p_mw",
        aggfunc = "sum",
    )
    loads_wide.index.name = None
    loads_wide = loads_wide.fillna(0.0)

    buses_red = set(n.buses.index)
    n_cargas  = 0

    for bus_name in loads_wide.columns:
        if bus_name not in buses_red:
            continue
        n.add("Load", f"load_{bus_name}", bus=bus_name)
        n_cargas += 1

    load_names   = [f"load_{b}" for b in loads_wide.columns if b in buses_red]
    loads_wide.columns = [f"load_{b}" for b in loads_wide.columns]
    cols_validas = [c for c in load_names if c in loads_wide.columns]
    n.loads_t.p_set = loads_wide[cols_validas]

    dem_max = loads_wide[cols_validas].sum(axis=1).max()
    print(f"  Buses con demanda : {n_cargas}")
    print(f"  Demanda maxima    : {dem_max:,.1f} MW")


# =============================================================================
# PASO 5 — Clustering para cada N
# =============================================================================

def correr_clustering(n):
    print(f"\n[5/6] Corriendo clustering espacial k-means ...")
    print(f"  Niveles de agregacion: {CLUSTER_SIZES}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    #  Eliminar columnas custom que no son estandar PyPSA y rompen el clustering
    COLS_CUSTOM_BUSES = [
        "v_mag_pu_psse", "v_ang_deg_psse", "bus_type",
        "ide", "ide_desc", "parent_bus_id", "name_geosadi", "bus_name_psse"
    ]
    for col in COLS_CUSTOM_BUSES:
        if col in n.buses.columns:
            n.buses.drop(columns=[col], inplace=True)

    resultados = {}

    for N in CLUSTER_SIZES:
        print(f"\n  --- K = {N} ---")

        # Correr kmeans_clustering nativo de PyPSA 
        if BUS_WEIGHTING == "p_nom":
            bus_weightings = n.generators.groupby("bus")["p_nom"].sum().reindex(n.buses.index).fillna(1.0)
        elif BUS_WEIGHTING == "demanda":
            bus_weightings = n.loads_t.p_set.mean().rename(lambda x: x.replace("load_", "")).reindex(n.buses.index).fillna(1.0)
        else:  # uniforme
            bus_weightings = pd.Series(1.0, index=n.buses.index)

        clustering = kmeans_clustering(n, n_clusters=N, bus_weightings=bus_weightings)
        
        nc  = clustering.network   # network clusterizado
        busmap = clustering.busmap  # Serie: bus_original -> cluster_id

        print(f"  Super-buses generados : {len(nc.buses)}")
        print(f"  Lineas equivalentes   : {len(nc.lines)}")

        # Guardar network clusterizado
        nc_path = os.path.join(OUTPUT_DIR, f"cluster_k{N}.nc")
        nc.export_to_netcdf(nc_path)
        print(f"  Network guardado      : cluster_k{N}.nc")

        resultados[N] = {"nc": nc, "busmap": busmap}

    return resultados


# =============================================================================
# PASO 6 — Exportar GeoPackage y summaries
# =============================================================================

def exportar_outputs(n, resultados):
    print(f"\n[6/6] Exportando GeoPackage y summaries ...")

    # Borrar .gpkg existente para evitar layers duplicados de corridas anteriores
    if os.path.isfile(GPKG_FILE):
        os.remove(GPKG_FILE)
        print(f"  .gpkg anterior eliminado — se genera uno nuevo limpio")
    # Mapa bus -> coordenadas originales
    buses_coords = n.buses[["x", "y"]].copy()
    buses_coords.columns = ["lon", "lat"]

    for N, res in resultados.items():
        nc     = res["nc"]
        busmap = res["busmap"]

        print(f"\n  Exportando K = {N} ...")

        # ------------------------------------------------------------------
        # Layer 1: buses originales coloreados por cluster
        # ------------------------------------------------------------------
        buses_df = buses_coords.copy()
        buses_df["cluster_id"] = busmap.reindex(buses_df.index)
        buses_df = buses_df.dropna(subset=["lat", "lon", "cluster_id"])
        buses_df["cluster_id"] = buses_df["cluster_id"].astype(int)

        gdf_buses = gpd.GeoDataFrame(
            buses_df.reset_index().rename(columns={"index": "bus_name"}),
            geometry=[Point(row["lon"], row["lat"]) for _, row in buses_df.iterrows()],
            crs=CRS,
        )

        gdf_buses.to_file(GPKG_FILE, layer=f"k{N}_buses", driver="GPKG")
        print(f"    Layer k{N}_buses      : {len(gdf_buses)} buses")

        # ------------------------------------------------------------------
        # Layer 2: centroides (super-buses)
        # ------------------------------------------------------------------
        centroids_df = nc.buses[["x", "y"]].copy()
        centroids_df.columns = ["lon", "lat"]
        centroids_df = centroids_df.dropna()
        centroids_df["cluster_id"] = range(len(centroids_df))

        # p_nom total por super-bus
        if len(nc.generators) > 0:
            pnom_por_bus = nc.generators.groupby("bus")["p_nom"].sum()
            centroids_df["p_nom_total_mw"] = centroids_df.index.map(pnom_por_bus).fillna(0.0)
        else:
            centroids_df["p_nom_total_mw"] = 0.0

        # n_buses por cluster
        n_buses_por_cluster = busmap.value_counts().to_dict()
        centroids_df["n_buses"] = centroids_df.index.map(n_buses_por_cluster).fillna(0).astype(int)

        gdf_centroids = gpd.GeoDataFrame(
            centroids_df.reset_index().rename(columns={"index": "super_bus"}),
            geometry=[Point(row["lon"], row["lat"]) for _, row in centroids_df.iterrows()],
            crs=CRS,
        )

        gdf_centroids.to_file(GPKG_FILE, layer=f"k{N}_centroids", driver="GPKG")
        print(f"    Layer k{N}_centroids  : {len(gdf_centroids)} super-buses")

        # ------------------------------------------------------------------
        # Layer 3: lineas equivalentes entre clusters
        # ------------------------------------------------------------------
        lineas_rows = []
        for line_name, line in nc.lines.iterrows():
            bus0 = line["bus0"]
            bus1 = line["bus1"]
            if bus0 not in centroids_df.index or bus1 not in centroids_df.index:
                continue
            lon0 = centroids_df.loc[bus0, "lon"]
            lat0 = centroids_df.loc[bus0, "lat"]
            lon1 = centroids_df.loc[bus1, "lon"]
            lat1 = centroids_df.loc[bus1, "lat"]
            if pd.isna(lon0) or pd.isna(lon1):
                continue
            lineas_rows.append({
                "line_name" : line_name,
                "bus0"      : bus0,
                "bus1"      : bus1,
                "s_nom_mw"  : line.get("s_nom", 0),
                "geometry"  : LineString([(lon0, lat0), (lon1, lat1)]),
            })

        if lineas_rows:
            gdf_lines = gpd.GeoDataFrame(lineas_rows, crs=CRS)
            gdf_lines.to_file(GPKG_FILE, layer=f"k{N}_lines", driver="GPKG")
            print(f"    Layer k{N}_lines      : {len(gdf_lines)} lineas equivalentes")
        else:
            print(f"    Layer k{N}_lines      : sin lineas para exportar")

        # ------------------------------------------------------------------
        # CSV summary
        # ------------------------------------------------------------------
        exportar_summary(nc, busmap, centroids_df, N)

    print(f"\n  GeoPackage final: {GPKG_FILE}")
    print(f"  Layers: {[f'k{N}_{t}' for N in CLUSTER_SIZES for t in ['buses','centroids','lines']]}")
    print(f"\n  Simbologia sugerida en QGIS:")
    print(f"    Buses    -> Categorizado por 'cluster_id'")
    print(f"    Centroids-> Tamanio proporcional a 'p_nom_total_mw': sqrt(p_nom_total_mw) / 5")
    print(f"    Lineas   -> Ancho proporcional a 's_nom_mw'")


def exportar_summary(nc, busmap, centroids_df, N):
    """Construye y guarda cluster_summary_k{N}.csv."""

    rows = []

    for cluster_id, centroid_row in centroids_df.iterrows():
        # Generadores del cluster
        gens_cluster = nc.generators[nc.generators["bus"] == cluster_id] if len(nc.generators) > 0 else pd.DataFrame()

        def sum_carriers(carriers):
            if gens_cluster.empty:
                return 0.0
            mask = gens_cluster["carrier"].isin(carriers)
            return gens_cluster.loc[mask, "p_nom"].sum()

        rows.append({
            "cluster_id"        : cluster_id,
            "centroid_lat"      : round(centroid_row["lat"], 4),
            "centroid_lon"      : round(centroid_row["lon"], 4),
            "n_buses"           : int(centroid_row["n_buses"]),
            "p_nom_hydro_mw"    : round(sum_carriers(CARRIERS_HYDRO),      1),
            "p_nom_nuclear_mw"  : round(sum_carriers(CARRIERS_NUCLEAR),    1),
            "p_nom_termica_mw"  : round(sum_carriers(CARRIERS_TERMICA),    1),
            "p_nom_wind_mw"     : round(sum_carriers(CARRIERS_WIND),       1),
            "p_nom_solar_mw"    : round(sum_carriers(CARRIERS_SOLAR),      1),
            "p_nom_bioenergia_mw": round(sum_carriers(CARRIERS_BIOENERGIA), 1),
            "p_nom_total_mw"    : round(sum_carriers(
                CARRIERS_HYDRO | CARRIERS_NUCLEAR | CARRIERS_TERMICA |
                CARRIERS_WIND  | CARRIERS_SOLAR   | CARRIERS_BIOENERGIA
            ), 1),
        })

    summary = pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)
    summary_path = os.path.join(OUTPUT_DIR, f"cluster_summary_k{N}.csv")
    summary.to_csv(summary_path, index=False)

    print(f"    Summary k{N}          : {summary_path}")
    print(f"      p_nom total sistema : {summary['p_nom_total_mw'].sum():,.1f} MW")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("21_network_clustering.py -- clustering espacial k-means")
    print("=" * 60)
    print(f"\nNiveles de agregacion: {CLUSTER_SIZES}")

    print("\n[0/6] Verificando inputs ...")
    verificar_inputs()

    n = cargar_network()
    agregar_generadores(n)
    agregar_perfiles(n)
    agregar_demanda(n)

    resultados = correr_clustering(n)
    exportar_outputs(n, resultados)

    print(f"\n{'='*60}")
    print(f"Clustering completado.")
    print(f"Outputs en: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
