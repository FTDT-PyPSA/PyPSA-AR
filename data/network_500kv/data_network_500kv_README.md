# data/network_500kv

Archivos procesados del pipeline de construcción de la red 500 kV.
Generados corriendo los scripts de `scripts/network_500kv/` en orden.

---

## Índice de archivos

| Archivo | Generado por | Descripción breve |
|---------|-------------|-------------------|
| `buses_500kv_raw.csv` | `01_parse_raw_buses.py` | Buses 500 kV extraídos del PSS/E |
| `lines_500kv_raw.csv` | `02_parse_raw_lines.py` | Líneas y compensadores 500 kV extraídos del PSS/E |
| `trafos_500kv_raw.csv` | `03_parse_raw_transformers.py` | Transformadores con al menos un lado en 500 kV |
| `buses_sec_raw.csv` | `04_parse_raw_buses_sec.py` | Buses secundarios (lado bajo de los transformadores) |
| `buses_final.csv` | `05_match_geosadi_coords.py` | Todos los buses con coordenadas geográficas |
| `lines_500kv_final.csv` | `06_match_geosadi_geometry.py` | Líneas con geometría WKT de GeoSADI |
| `buses_PSSE_vs_geosadi.xlsx` | Manual | Diccionario de matching bus PSS/E → coordenadas GeoSADI |
| `manual_line_mappings.csv` | Manual | Diccionario de mapping line_key → geosadi_line_id |
| `topology_report.csv` | `07_validate_topology.py` | Reporte de problemas topológicos |
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
| `ide_desc` | Descripción del tipo de bus |
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
| `in_service` | True si la rama está en servicio |

---

### `trafos_500kv_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Transformadores con al menos un devanado en 500 kV. Los transformadores de 3 devanados
se descomponen en 2 transformadores de 2 devanados usando el devanado de 500 kV como
referencia común. Ver docstring de `03_parse_raw_transformers.py` para la lógica completa.

| Campo | Descripción |
|-------|-------------|
| `trafo_key` | Identificador legible: `BUS_I-BUS_J-CKT` |
| `bus_i` | Bus 500 kV (siempre el lado de alta tensión) |
| `bus_j` | Bus secundario (lado de baja tensión) |
| `ckt` | Número de circuito |
| `origin` | `2W` (original) o `3W_decomp` (descompuesto de 3 devanados) |
| `r_pu` / `x_pu` | Impedancias en pu (Sbase=100 MVA) |
| `sbase_mva` | Potencia base del transformador en MVA (equivale a `s_nom` en PyPSA) |
| `in_service` | True si el transformador está en servicio |

---

### `buses_sec_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Buses secundarios: todos los buses que aparecen como `bus_j` en `trafos_500kv_raw.csv`.
Incluye tanto barras de red (33–345 kV) como terminales de generador (11–22 kV).

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID numérico en PSS/E |
| `bus_name` | Nombre generado: `PARENT_kVkV` o `PARENT_kVkV_N` |
| `bus_name_psse` | Nombre original del bus en el PSS/E |
| `baskv_kv` | Tensión base (kV) |
| `ide` | Tipo de bus PSS/E: 1=PQ, 2=PV, 3=slack, 4=isolated |
| `ide_desc` | Descripción del tipo de bus |
| `vm_pu` | Módulo de tensión del caso base (pu) |
| `va_deg` | Ángulo de tensión del caso base (grados) |
| `parent_bus_id` | `bus_id` del bus 500 kV al que conecta vía transformador |

---

### `buses_final.csv`
**Fuente:** `buses_500kv_raw.csv` + `buses_sec_raw.csv` + `buses_PSSE_vs_geosadi.xlsx`

Consolidación de todos los buses del modelo con coordenadas geográficas.
Los buses 500 kV reciben coordenadas del diccionario manual. Los buses secundarios
heredan las coordenadas del bus 500 kV padre (misma estación física).

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID numérico en PSS/E |
| `bus_name` | Nombre del bus en el modelo |
| `bus_name_psse` | Nombre original PSS/E (solo buses secundarios) |
| `bus_type` | `500kV` o `secundario` |
| `baskv_kv` | Tensión base (kV) |
| `ide` / `ide_desc` | Tipo de bus PSS/E y descripción |
| `vm_pu` / `va_deg` | Tensión del caso base PSS/E |
| `lat` / `lon` | Coordenadas geográficas (WGS84) |
| `parent_bus_id` | Bus 500 kV padre (NaN para buses 500 kV) |
| `name_geosadi` | Nombre GeoSADI asignado (solo buses 500 kV) |

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
**Fuente:** revisión manual

Diccionario de coordenadas para los 95 buses 500 kV del PSS/E.
Usado por `05_match_geosadi_coords.py` como fuente de verdad para coordenadas.

---

### `manual_line_mappings.csv`
**Fuente:** revisión manual

23 entradas de mapping manual `line_key → geosadi_line_id` para líneas que no pueden
resolverse automáticamente: compensadores serie, nodos internos de subestación y
circuitos paralelos ambiguos. Usado por `06_match_geosadi_geometry.py`.

---

### `topology_report.csv`
**Fuente:** `07_validate_topology.py`

Reporte de problemas topológicos. Si la red está limpia el archivo está vacío o no existe.

| Campo | Descripción |
|-------|-------------|
| `tipo` | `bus_aislado` / `isla_desconectada` / `sin_rating` / `linea_huerfana` / `trafo_huerfano` |
| `elemento` | Nombre del elemento con el problema |
| `detalle` | Descripción del problema |

---

### `conexiones_internacionales.md`
Tabla de interconexiones de Argentina con Bolivia, Brasil, Chile, Paraguay y Uruguay
presentes en el PSS/E. Referencia para cuando se incorporen esos flujos al modelo.
