# PyPSA-AR Roadmap

Objetivo: modelo calibrado y reproducible de la red eléctrica argentina usando PyPSA.

Estrategia de construcción: arrancar con la red 500 kV completa y cerrarla antes de
incorporar niveles de tensión inferiores. Cada nivel se valida antes de avanzar al siguiente.

---

## Fase 0 — Repositorio y estructura ✅ COMPLETADA

- Repositorio GitHub inicializado
- Estructura de carpetas definida
- Documentación base creada
- Entorno reproducible configurado (pypsa-earth-lock en WSL)

---

## Fase 1 — Auditoría PyPSA-Earth para Argentina ✅ COMPLETADA

Objetivo: entender qué modelaba PyPSA-Earth para AR y decidir si reutilizar o reemplazar.

Resultado: se decidió reemplazar toda la data de OSM por GeoSADI + PSS/E.
Razones documentadas en `docs/aprendizaje_pypsaearth_ar.md`.

Hallazgos clave:
- PyPSA-Earth tiene 125 transformadores vs 1.132 reales (11% cobertura)
- Líneas 500 kV con tipo de conductor europeo (380 kV)
- Sin impedancias activas (r=0, x=0)

---

## Fase 2 — Construcción red 500 kV ✅ COMPLETADA

Fuentes: GeoSADI (geometría) + PSS/E ver2526pid.raw (topología e impedancias)

| Script | Descripción | Estado |
|--------|-------------|--------|
| `01_parse_raw_buses.py` | Extrae buses 500 kV del PSS/E | ✅ |
| `02_parse_raw_lines.py` | Extrae líneas 500 kV del PSS/E | ✅ |
| `03_parse_raw_transformers.py` | Extrae transformadores con lado en 500 kV | ✅ |
| `04_parse_raw_buses_sec.py` | Extrae buses secundarios de los transformadores | ✅ |
| `05_match_geosadi_coords.py` | Asigna coordenadas y consolida todos los buses | ✅ |
| `06_match_geosadi_geometry.py` | Asigna geometría WKT a líneas | ✅ |
| `07_validate_topology.py` | Valida topología de la red | ✅ |
| `07b_export_qgis.py` | Exporta a GeoPackage para QGIS | ✅ |
| `08_build_pypsa_network.py` | Construye objeto PyPSA Network | ✅ |

Estado de la red 500 kV:
- 95 buses 500 kV + 249 buses secundarios = 344 buses en el network
- 103 líneas activas (incluye compensadores serie)
- 300 transformadores
- Fusión de acopladores de barra aplicada: 17 buses fusionados al representante del grupo
- 1 componente conexa, 0 buses aislados
- Interconexión Argentina-Brasil incluida: Link `importacion_brasil` (p_nom=2200 MW)

---

## Fase 3 — Generación y demanda 500 kV ✅ COMPLETADA

Objetivo: incorporar generación y demanda reales 2024 al modelo y validar con flujo DC.

| Script | Descripción | Estado |
|--------|-------------|--------|
| `09_map_generators.py` | Mapea generadores PSS/E → nodos del modelo | ✅ |
| `10_map_loads.py` | Mapea cargas PSS/E → nodos del modelo | ✅ |
| `10b_visualize_qgis.py` | Exporta balance generación/carga a QGIS | ✅ |
| `11_add_geo_to_generators.py` | Asigna coordenadas GeoSADI a generadores | ✅ |
| `12_build_generators_final.py` | Tabla definitiva de generadores para PyPSA | ✅ |
| `12b_export_qgis_generators.py` | Agrega layer de centrales al GeoPackage | ✅ |
| `12c_test_snapshot.py` | Validación power flow Newton-Raphson con snapshot PSS/E | ✅ |
| `13_clean_valores_2024.py` | Limpieza y normalización de VALORES_2024.csv | ✅ |
| `14_detectar_conflictos_generadores.py` | Detecta discrepancias PSS/E vs CAMMESA | ✅ |
| `14b_build_generators_2024.py` | Generadores con p_nom real 2024 desde CAMMESA | ✅ |
| `15_build_loads_2024.py` | Demanda horaria 2024 por bus en formato largo | ✅ |
| `16_snapshot_dc_pico2024.py` | Validación DC en snapshot de pico de demanda | ✅ |
| `17_build_gen_profiles_2024.py` | Perfiles horarios de disponibilidad (p_max_pu) | ✅ |

Resultados del snapshot de validación (01/02/2024 14:00 — pico de demanda 2024):
- Generación despachada: 26.374 MW | Inyección del slack: 1.013 MW | Demanda: 27.439 MW
- Brecha generación/demanda explicada por importaciones de Brasil (~2.267 MW, no modeladas)
- Mix: 59% térmica, 26% hidro, 8% nuclear, 5% eólica, 4% solar
- 1 línea al 133% de su rating (C.COSTA-P.BAND.-1) — congestión consistente con la
  limitación de modelar solo red 500 kV sin los paralelos de niveles inferiores

---

## Fase 4 — Costos marginales y optimización ⚠️ EN CURSO

Objetivo: incorporar costos marginales, correr el despacho económico 2024 y analizar resultados.

| Script | Descripción | Estado |
|--------|-------------|--------|
| `18_diagnostico_costos_marginales.py` | Auditoría de cobertura de costos por unidad | ✅ |
| `18B_build_costos_marginales_2024.py` | Tabla de costos marginales fijos anuales | ✅ |
| `19_run_optimization.py` | Despacho económico DC (OPF) — `n.optimize()` | ✅ construido, pendiente de correr año completo |
| `20_analyze_results.py` | Análisis de resultados vs datos reales CAMMESA | 🔲 pendiente |

Notas:
- Costos pendientes: ~171 unidades (principalmente hidro) con costo=0 hasta que equipo de trabajo complete el archivo de diagnóstico
- Script 19 parametrizado: período configurable (`FECHA_INICIO`/`FECHA_FIN`), chunking por días (`CHUNK_DIAS`), load shedding virtual para garantizar factibilidad
- Script 20 levantará el `.nc` de resultados sin recorrer la optimización

---

## Fase 4b — Clustering espacial ✅ COMPLETADA

Objetivo: generar versiones simplificadas de la red para análisis de largo plazo.

| Script | Descripción | Estado |
|--------|-------------|--------|
| `21_network_clustering.py` | Clustering k-means nativo PyPSA | ✅ |

Resultados:
- Clustering corrido para K=10, K=20, K=50 usando `kmeans_clustering` de PyPSA 0.30.3
- Criterio actual: pesos uniformes (clustering puramente geográfico)
- Redes clusterizadas exportadas como `.nc` — funcionales para `n.optimize()` futura
- Visualización en QGIS: `data/network_500kv/clusters/clusters.qgz`
- Criterio de agrupamiento alternativo (`BUS_WEIGHTING = "p_nom"` o `"demanda"`) disponible como parámetro configurable

---

## Fase 5 — Incorporar niveles 220, 330, 132 kV 🔲 PENDIENTE

Mismo pipeline que 500 kV, nivel por nivel.
Scripts 01–08 son reutilizables con distintos filtros de tensión.
Incorporar transformadores inter-nivel.

---

## Fase 6 — Escenarios de expansión 🔲 PENDIENTE

Con el modelo base validado, correr escenarios de política energética y expansión de red.
Requiere previamente: modelo calibrado (Fase 4), definición de escenarios de demanda futura,
curvas de costo de nuevas tecnologías y decisión sobre niveles de clustering a utilizar.

Fecha límite del proyecto: 30/04/2026
