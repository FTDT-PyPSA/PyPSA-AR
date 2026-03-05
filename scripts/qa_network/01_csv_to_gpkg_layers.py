import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely import wkt

BASE = "/mnt/c/Work/pypsa-ar-base/outputs/elec_nc_inspection"
OUT_GPKG = os.path.join(BASE, "pypsa_elec_layers.gpkg")
CRS = "EPSG:4326"

def voltage_class_kv(v):
    if pd.isna(v):
        return "unknown"
    v = float(v)
    # incluyo 345 como clase propia
    if v >= 500: return "500 kV"
    if v >= 345: return "345 kV"
    if v >= 330: return "330 kV"
    if v >= 220: return "220 kV"
    if v >= 132: return "132 kV"
    if v >= 110: return "110 kV"
    if v >= 66:  return "66 kV"
    if v >= 35:  return "35 kV"
    return "<35 kV"

def read_csv(path, index_col_name):
    df = pd.read_csv(path)
    # si trae Unnamed: 0 lo borro
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])
    # seteo índice si existe
    if index_col_name in df.columns:
        df = df.set_index(index_col_name, drop=True)
    return df

def pick_xy(buses_df):
    # preferimos x/y si están y no son NaN, sino lon/lat
    if "x" in buses_df.columns and "y" in buses_df.columns:
        if buses_df["x"].notna().all() and buses_df["y"].notna().all():
            return "x", "y"
    # fallback a lon/lat
    return "lon", "lat"

def lines_from_buses(df_edges, buses_xy, a="bus0", b="bus1"):
    # arma LineString directo de bus0-bus1
    def make_line(row):
        u = row[a]; v = row[b]
        if u not in buses_xy.index or v not in buses_xy.index:
            return None
        x0, y0 = buses_xy.loc[u, ["X", "Y"]]
        x1, y1 = buses_xy.loc[v, ["X", "Y"]]
        if pd.isna(x0) or pd.isna(y0) or pd.isna(x1) or pd.isna(y1):
            return None
        return LineString([(x0, y0), (x1, y1)])
    return df_edges.apply(make_line, axis=1)

# =========================
# Load CSVs
# =========================
buses = read_csv(os.path.join(BASE, "buses_elec.csv"), "Bus")
lines = read_csv(os.path.join(BASE, "lines_elec.csv"), "Line")
trafos = read_csv(os.path.join(BASE, "transformers_elec.csv"), "Transformer")
loads = read_csv(os.path.join(BASE, "loads_elec.csv"), "Load")
gens  = read_csv(os.path.join(BASE, "generators_elec.csv"), "Generator")

# =========================
# Buses -> points
# =========================
xcol, ycol = pick_xy(buses)
buses["v_kv"] = pd.to_numeric(buses["v_nom"], errors="coerce")
buses["v_class"] = buses["v_kv"].apply(voltage_class_kv)

gdf_buses = gpd.GeoDataFrame(
    buses.copy(),
    geometry=[Point(xy) for xy in zip(buses[xcol], buses[ycol])],
    crs=CRS
)

# tabla auxiliar para construir líneas y ubicar loads/gens
buses_xy = pd.DataFrame({"X": buses[xcol], "Y": buses[ycol]}, index=buses.index)

# =========================
# Lines -> geometry (WKT o bus0/bus1)
# =========================
lines["v_kv"] = pd.to_numeric(lines["v_nom"], errors="coerce")
lines["v_class"] = lines["v_kv"].apply(voltage_class_kv)

if "geometry" in lines.columns and lines["geometry"].notna().any():
    # intenta WKT
    def parse_wkt(s):
        if pd.isna(s) or str(s).strip() == "":
            return None
        try:
            return wkt.loads(s)
        except Exception:
            return None
    geom = lines["geometry"].apply(parse_wkt)
    # si algunas fallan, las completamos con bus0-bus1
    missing = geom.isna()
    if missing.any():
        geom2 = lines_from_buses(lines[missing], buses_xy, "bus0", "bus1")
        geom.loc[missing] = geom2
else:
    geom = lines_from_buses(lines, buses_xy, "bus0", "bus1")

gdf_lines = gpd.GeoDataFrame(lines.copy(), geometry=geom, crs=CRS)
gdf_lines = gdf_lines[gdf_lines.geometry.notna()].copy()


# =========================
# Transformers -> POINTS en bus0 (cambio mínimo)
# =========================
# (No trae v_nom: lo inferimos por max(v_nom bus0, v_nom bus1))
def infer_v_from_buses(row):
    u = row["bus0"]; v = row["bus1"]
    vu = buses.loc[u, "v_kv"] if u in buses.index else None
    vv = buses.loc[v, "v_kv"] if v in buses.index else None
    vals = [x for x in [vu, vv] if pd.notna(x)]
    return max(vals) if vals else None

trafos["v_kv"] = trafos.apply(infer_v_from_buses, axis=1)
trafos["v_class"] = trafos["v_kv"].apply(voltage_class_kv)

def trafo_point_from_bus0(row):
    b = row["bus0"]
    if b not in buses_xy.index:
        return None
    x, y = buses_xy.loc[b, ["X", "Y"]]
    if pd.isna(x) or pd.isna(y):
        return None
    return Point(x, y)

geom_t = trafos.apply(trafo_point_from_bus0, axis=1)

gdf_trafos = gpd.GeoDataFrame(trafos.copy(), geometry=geom_t, crs=CRS)
gdf_trafos = gdf_trafos[gdf_trafos.geometry.notna()].copy()

# =========================
# Loads / Generators -> points at bus
# =========================
def points_on_bus(df, bus_col="bus"):
    def make_pt(row):
        b = row[bus_col]
        if b not in buses_xy.index:
            return None
        x, y = buses_xy.loc[b, ["X", "Y"]]
        if pd.isna(x) or pd.isna(y):
            return None
        return Point(x, y)
    geom = df.apply(make_pt, axis=1)
    gdf = gpd.GeoDataFrame(df.copy(), geometry=geom, crs=CRS)
    return gdf[gdf.geometry.notna()].copy()

gdf_loads = points_on_bus(loads, "bus")
gdf_gens  = points_on_bus(gens,  "bus")

# (opcional) a loads/gens le agrego v del bus para colorear también
for gdf in [gdf_loads, gdf_gens]:
    gdf["v_kv"] = gdf["bus"].map(buses["v_kv"])
    gdf["v_class"] = gdf["v_kv"].apply(voltage_class_kv)

# =========================
# Write GPKG (borra si existe)
# =========================
if os.path.exists(OUT_GPKG):
    os.remove(OUT_GPKG)

gdf_buses.to_file(OUT_GPKG, layer="buses", driver="GPKG")
gdf_lines.to_file(OUT_GPKG, layer="lines", driver="GPKG")
gdf_trafos.to_file(OUT_GPKG, layer="transformers", driver="GPKG")
gdf_loads.to_file(OUT_GPKG, layer="loads", driver="GPKG")
gdf_gens.to_file(OUT_GPKG, layer="generators", driver="GPKG")

print("OK ->", OUT_GPKG)
print("Layers: buses, lines, transformers, loads, generators")
print("Counts:",
      "buses", len(gdf_buses),
      "lines", len(gdf_lines),
      "trafos", len(gdf_trafos),
      "loads", len(gdf_loads),
      "gens", len(gdf_gens))