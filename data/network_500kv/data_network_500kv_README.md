# data/network_500kv

Archivos procesados del pipeline de construcción de la red 500 kV.
Generados corriendo los scripts de `scripts/network_500kv/` en orden.

---

## Índice de archivos

| Archivo | Generado por | Descripción breve |
|---------|-------------|-------------------|
| `buses_500kv_raw.csv` | `01_parse_raw_buses.py` | Buses 500 kV extraídos del PSS/E |
| `lines_500kv_raw.csv` | `02_parse_raw_lines.py` | Líneas y compensadores 500 kV extraídos del PSS/E |
| `buses_500kv_final.csv` | `03_match_geosadi_coords.py` | Buses con coordenadas geográficas de GeoSADI |
| `lines_500kv_final.csv` | `04_match_geosadi_geometry.py` | Líneas con geometría WKT de GeoSADI |
| `buses_PSSE_vs_geosadi.xlsx` | Manual | Diccionario de matching bus PSS/E → nombre GeoSADI |
| `manual_line_mappings.csv` | Manual | Diccionario de mapping line_key → geosadi_line_id |
| `topology_report.csv` | `05_validate_topology.py` | Reporte de problemas topológicos |
| `conexiones_internacionales.md` | Manual | Interconexiones con países vecinos en el PSS/E |

---

## Detalle

### `buses_500kv_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Buses 500 kV del caso PSS/E con sus parámetros eléctricos del caso base.
Un registro por bus. Excluye buses IDE=4 (aislados) e internacionales.

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID numérico en PSS/E |
| `bus_name` | Nombre del bus |
| `baskv_kv` | Tensión base (kV) |
| `ide` | Tipo: 1=PQ, 2=PV, 3=slack |
| `area` | Área eléctrica CAMMESA |
| `vm_pu` | Módulo de tensión del caso base (pu) |
| `va_deg` | Ángulo de tensión del caso base (grados) |

---

### `lines_500kv_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Líneas y compensadores serie 500 kV con impedancias y ratings del caso PSS/E.

| Campo | Descripción |
|-------|-------------|
| `line_key` | Identificador legible: `BUS_I-BUS_J-CKT` |
| `bus_i` / `bus_j` | IDs de buses extremos |
| `ckt` | Número de circuito (1, 2, 3...) |
| `r_pu` / `x_pu` / `b_pu` | Impedancias en pu (Sbase=100 MVA) |
| `ratea_mva` | Capacidad térmica en MVA (NaN si no definida) |
| `len_km` | Longitud en km |
| `element_type` | `line` o `series_compensator` |
| `in_service` | True si ST=1 en el raw |

---

### `buses_500kv_final.csv`
**Fuente:** `buses_500kv_raw.csv` + GeoSADI `estaciones_transformadoras.csv`

Buses con coordenadas geográficas asignadas. Extiende `buses_500kv_raw.csv` con:

| Campo | Descripción |
|-------|-------------|
| `name_geosadi` | Nombre de la estación GeoSADI asignada |
| `lat` / `lon` | Coordenadas geográficas (WGS84) |
| `match_score` | Score de similitud del matching [0-1] |
| `match_status` | `ok` / `consultar` / `pendiente` / `manual` |

---

### `lines_500kv_final.csv`
**Fuente:** `lines_500kv_raw.csv` + GeoSADI `lineas_alta_tension.geojson`

Líneas con geometría WKT asignada. Extiende `lines_500kv_raw.csv` con:

| Campo | Descripción |
|-------|-------------|
| `geo_nombre` | Nombre de la línea GeoSADI asignada |
| `match_status` | `directo` / `paralela` / `manual_geo` / `compensador` / `pendiente_bus` |
| `geometry` | Geometría WKT (LINESTRING, WGS84) |

---

### `buses_PSSE_vs_geosadi.xlsx`
**Fuente:** revisión manual del equipo

Diccionario de matching manual entre los 96 buses PSS/E y sus equivalentes en GeoSADI.
Usado por `03_match_geosadi_coords.py` para los casos donde el matching automático no es confiable.

---

### `manual_line_mappings.csv`
**Fuente:** revisión manual del equipo

23 entradas de mapping manual `line_key → geosadi_line_id` para líneas que no pueden resolverse
automáticamente: compensadores serie, nodos internos de subestación y circuitos paralelos ambiguos.
Usado por `04_match_geosadi_geometry.py`.

---

### `topology_report.csv`
**Fuente:** `05_validate_topology.py`

Reporte de problemas topológicos. Si la red está limpia el archivo está vacío o no existe.

| Campo | Descripción |
|-------|-------------|
| `tipo` | `bus_aislado` / `isla_desconectada` / `sin_rating` / `linea_huerfana` |
| `elemento` | Nombre del elemento con el problema |
| `detalle` | Descripción del problema |

---

### `conexiones_internacionales.md`
Tabla de interconexiones de Argentina con Bolivia, Brasil, Chile, Paraguay y Uruguay
presentes en el PSS/E. Referencia para cuando se incorporen esos flujos al modelo.
