# PyPSA-AR Architecture

## Objetivo

Construir un modelo calibrado y reproducible de la red eléctrica argentina de alta tensión usando PyPSA.

La estrategia es construir la red nivel por nivel, validando cada uno antes de incorporar el siguiente.
La red 500 kV es el backbone del SADI y el punto de partida.

---

## Scope del modelo

**v0.1 — Red 500 kV completa:**
- Todos los buses 500 kV y sus buses secundarios (lado bajo de transformadores)
- Líneas con impedancias reales del PSS/E (r, x, b en pu, Sbase=100 MVA)
- Compensadores serie identificados y modelados como Line con x negativo
- Transformadores de 3 devanados descompuestos en 2 × 2W con bus 500 kV como referencia
- Generación y demanda mapeadas a buses según nivel de tensión

**v0.2 y siguientes:**
- Incorporar niveles 220, 330, 132 kV uno a uno
- Transformadores inter-nivel
- Generación y demanda completas

**Fuera de scope:**
- Distribución (MT/BT)
- Mercado spot / precios marginales (por ahora)

---

## Fuentes de datos

| Componente | Fuente | Formato |
|------------|--------|---------|
| Topología e impedancias | PSS/E ver2526pid.raw (CAMMESA) | .raw |
| Coordenadas de buses | GeoSADI — estaciones_transformadoras | .csv |
| Geometría de líneas | GeoSADI — lineas_alta_tension | .geojson |
| Generación y demanda | CAMMESA | pendiente |

GeoSADI: https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

---

## Pipeline de construcción

```
PSS/E .raw ──→ 01_parse_raw_buses.py          ──→ buses_500kv_raw.csv
               02_parse_raw_lines.py           ──→ lines_500kv_raw.csv
               03_parse_raw_transformers.py    ──→ trafos_500kv_raw.csv
               04_parse_raw_buses_sec.py       ──→ buses_sec_raw.csv
                        │
GeoSADI ────→ 05_match_geosadi_coords.py      ──→ buses_final.csv
              06_match_geosadi_geometry.py     ──→ lines_500kv_final.csv
                        │
              07_validate_topology.py          ──→ topology_report.csv
              07b_export_qgis.py               ──→ red_500kv_qgis.gpkg
                        │
              08_build_pypsa_network.py        ──→ network_500kv.nc
```

Todos los scripts corren desde WSL con el entorno `pypsa-earth-lock`.
Rutas en `/mnt/c/Work/pypsa-ar-base/`.

---

## Capas del modelo PyPSA

### 1. Red física
- Buses 500 kV con coordenadas GeoSADI y nivel de tensión
- Buses secundarios heredando coordenadas del bus 500 kV padre
- Líneas con r, x, b, s_nom, length
- Compensadores serie como Line con x negativo
- Transformadores con x, s_nom

### 2. Generación
- Centrales mapeadas a buses por nivel de tensión
- Parámetros: p_nom, carrier, marginal_cost, efficiency
- Perfiles de disponibilidad para renovables

### 3. Demanda
- Perfiles horarios 8760h (año base 2024)
- Desagregados por nodo

### 4. Calibración
- Simulación DC power flow
- Comparación despacho simulado vs CAMMESA
- Target: error ≤ ±5% por tecnología

---

## Principios de diseño

- **Reproducibilidad**: todo el pipeline es scripteable desde el .raw hasta el .nc
- **Fuentes primarias**: GeoSADI + PSS/E son la fuente de verdad, no OSM
- **Modularidad**: cada nivel de tensión se construye y valida por separado
- **Git liviano**: solo scripts, documentación y CSVs de data procesada. Sin .nc ni .raw
