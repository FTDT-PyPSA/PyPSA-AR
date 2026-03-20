# PyPSA-AR Architecture

## Objetivo

Construir un modelo calibrado y reproducible de la red eléctrica argentina de alta tensión usando PyPSA.

La estrategia es construir la red nivel por nivel, validando cada uno antes de incorporar el siguiente.
La red 500 kV es el backbone del SADI y el punto de partida.

---

## Scope del modelo

**v0.1 — Red 500 kV completa (estado actual):**
- Todos los buses 500 kV y sus buses secundarios (lado bajo de transformadores)
- Líneas con impedancias reales del PSS/E (r, x, b en pu, Sbase=100 MVA)
- Compensadores serie identificados y modelados como Line con x negativo
- Transformadores de 3 devanados descompuestos en 2 × 2W con bus 500 kV como referencia
- Fusión de acopladores de barra (series_compensator con r=0): buses internos colapsados
  al representante del grupo antes de construir el network
- 626 unidades generadoras con p_nom desde datos reales CAMMESA 2024
- Demanda horaria 2024 por bus (72 buses, 8784 horas)
- Perfiles de disponibilidad horaria (p_max_pu) para todas las unidades generadoras

**v0.2 y siguientes:**
- Incorporar niveles 220, 330, 132 kV uno a uno
- Transformadores inter-nivel
- Generación y demanda completas

**Fuera de scope:**
- Distribución (MT/BT)


---

## Fuentes de datos

| Componente | Fuente | Formato |
|------------|--------|---------|
| Topología e impedancias | PSS/E ver2526pid.raw (CAMMESA) | .raw |
| Coordenadas de buses | GeoSADI — estaciones_transformadoras | .geojson |
| Geometría de líneas | GeoSADI — lineas_alta_tension | .geojson |
| Generación horaria 2024 | CAMMESA — VALORES_2024.csv | .csv |
| Demanda horaria 2024 | Archivo interno — Dda_horaria_x_trafo_2024.csv | .csv |
| Costos marginales | pendiente |

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
                        │
              09_map_generators.py             ──→ generators_mapped.csv
              10_map_loads.py                  ──→ loads_mapped.csv
              10b_visualize_qgis.py            ──→ balance_gen_carga.gpkg
              11_add_geo_to_generators.py      ──→ generators_readypypsa.csv
              12_build_generators_final.py     ──→ generators_final.csv
              12b_export_qgis_generators.py    ──→ layer centrales en .gpkg
              12c_test_snapshot.py             ──→ (validación — sin output)
                        │
CAMMESA ────→ 13_clean_valores_2024.py        ──→ valores_2024_clean.csv *
              14_detectar_conflictos.py        ──→ conflictos_psse_cammesa.csv
              14b_build_generators_2024.py     ──→ generators_2024.csv
              15_build_loads_2024.py           ──→ loads_2024.csv
              16_snapshot_dc_pico2024.py       ──→ (validación DC — sin output)
              17_build_gen_profiles_2024.py    ──→ gen_profiles_2024.csv *

* Archivos externos a GitHub por tamaño
```

---

## Capas del modelo PyPSA

### 1. Red física
- Buses 500 kV con coordenadas GeoSADI y nivel de tensión
- Buses secundarios heredando coordenadas del bus 500 kV padre
- Líneas con r, x, b, s_nom (desde ratea_mva del PSS/E)
- Compensadores serie como Line con x negativo
- Transformadores con x, s_nom

### 2. Generación
- 626 unidades generadoras mapeadas a buses del network
- `p_nom` por unidad: percentil 95 de POT_DISP anual CAMMESA 2024, distribuido
  proporcionalmente al pt_mw del PSS/E entre las unidades de cada central
- `p_max_pu` horario: ENERGIA/p_nom para solar, eólica, biogas y biomass;
  POT_DISP/p_nom para el resto
- Carriers: ocgt, steam, ccgt, hydro, nuclear, wind, solar, diesel, biogas, biomass, pumped_hydro
- `marginal_cost` por unidad: pendiente (script 18)

### 3. Demanda
- Perfiles horarios 8784h (año 2024, bisiesto)
- 72 buses con demanda asignada
- Fuente: Dda_horaria_x_trafo_2024.csv  — demanda por transformador de distribución

### 4. Validación
- Flujo DC linealizado (n.lpf()) sobre snapshot de pico de demanda (01/02/2024 14:00)
- Slack bus: ATUCHA 2_21kV (bus 2620, terminal de máquina nuclear, referencia del PSS/E)

### 5. Optimización (pendiente)
- n.optimize() sobre las 8784 horas de 2024
- Objetivo: minimizar costo total de generación
- Restricciones: límites de capacidad, p_max_pu horario, límites de transmisión

---

## Decisiones de modelado

### Red
- Impedancias en pu (Sbase=100 MVA confirmado en encabezado del PSS/E)
- Conversión a unidades físicas: Z_base = baskv² / S_base por línea
- Acopladores de barra fusionados en memoria — los CSVs originales no se modifican
- s_nom desde ratea_mva del PSS/E (rating térmico operativo, puede ser conservador
  respecto a la capacidad térmica real del conductor)

### Generación
- p_nom desde percentil 95 de POT_DISP — evita outliers sin descartar picos reales
- Yacyretá: CAMMESA reporta la central entera; se distribuye por p_nom entre las 20 unidades
- Salto Grande (SGDE): factor 0.5 sobre POT_DISP (central binacional Argentina/Uruguay)
- Unidades sin match en CAMMESA: excluidas del modelo
- Importaciones internacionales (ej: Brasil ~2.267 MW): no modeladas en esta versión

### Flujo DC
- Aproximación DC estándar: sin pérdidas, ángulos pequeños
- El slack absorbe el desbalance generación/demanda (diferencia entre p_set despachado
  y demanda total, explicada principalmente por importaciones no modeladas)

---

## Principios de diseño

- **Reproducibilidad**: todo el pipeline es scripteable desde el .raw hasta el .nc
- **Fuentes primarias**: GeoSADI + PSS/E son la fuente de verdad, no OSM
- **Modularidad**: cada nivel de tensión se construye y valida por separado
- **Git liviano**: solo scripts, documentación y CSVs de data procesada. Sin .nc ni archivos pesados
