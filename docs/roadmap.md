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

## Fase 2 — Construcción red 500 kV ✅ EN CURSO

Fuentes: GeoSADI (geometría) + PSS/E ver2526pid.raw (topología e impedancias)

Scripts desarrollados:

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
| `08_build_pypsa_network.py` | Construye objeto PyPSA Network | 🔲 |

Estado actual de la red 500 kV:
- 95 buses 500 kV + 266 buses secundarios = 361 buses totales
- 122 líneas (105 en servicio, 17 compensadores serie)
- 301 transformadores (65 de 2W + 118 de 3W descompuestos en 2 × 2W)
- sin_match = 0 en geometría
- Red 500 kV: 1 componente conexa, 0 buses aislados

Pendientes antes de cerrar la fase:
- Resolver T PEPE (1 trafo huérfano, 2 líneas pendiente_bus)
- Script 08: construir objeto PyPSA con impedancias reales

---

## Fase 3 — Generación y demanda 500 kV 🔲 PENDIENTE

Objetivo: incorporar generación y demanda para la red 500 kV y verificar que el modelo converge.

Tareas:
- Mapear centrales eléctricas a buses (500 kV o secundarios según corresponda)
- Asignar perfiles de demanda por nodo
- Correr simulación y verificar convergencia

---

## Fase 4 — Incorporar niveles 220, 330, 132 kV 🔲 PENDIENTE

Mismo pipeline que 500 kV, nivel por nivel.
Scripts 01–08 son reutilizables con distintos filtros de tensión.
Incorporar transformadores inter-nivel.

---

## Fase 5 — Generación y demanda completas 🔲 PENDIENTE

- 436 centrales del GeoSADI (hidro, eólica, solar incluidas)
- Perfiles horarios 8760h año base 2024
- Datos CAMMESA

---

## Fase 6 — Calibración año base 2024 🔲 PENDIENTE

- Simulación completa 8760h
- Comparar despacho simulado vs CAMMESA por tecnología
- Ajustar costos variables hasta match ±5%
- Validar límites de transmisión

Fecha límite del proyecto: 30/04/2026
