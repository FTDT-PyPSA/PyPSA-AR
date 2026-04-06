# PyPSA-AR-BASE

Modelo reproducible de la red eléctrica argentina de alta tensión usando PyPSA.

**Estado actual:** Scripts 01→19 y 21 finalizados. Red 500 kV construida, generación y demanda horaria 2024 incorporadas, costos marginales asignados, despacho económico DC listo para correr, clustering espacial completado.
**Fecha límite:** 30/04/2026

---

## Objetivo

Construir un modelo calibrado del SADI (Sistema Argentino de Interconexión) que permita:
- Replicar el despacho histórico 2024 contra datos CAMMESA
- Analizar restricciones de transmisión
- Servir de base para escenarios de expansión y política energética

Estrategia: construir nivel por nivel (500 kV → 220/330 kV → 132 kV), validando cada uno antes de avanzar.

---

## Entorno de trabajo

### Por qué WSL + Windows

El proyecto usa **WSL (Ubuntu)** para ejecutar los scripts y **Windows (Cursor o VSCode)** para editarlos.
Esta combinación no es accidental:

- PyPSA y sus dependencias (especialmente solvers lineales) funcionan de forma más estable en Linux
- El entorno `pypsa-earth-lock` fija las versiones de todas las librerías para garantizar reproducibilidad entre máquinas del equipo
- Cursor y VSCode en Windows corren en WSL sin fricción

**No usar Python de Windows ni un venv paralelo** — los scripts asumen rutas `/mnt/c/...` y el entorno conda de WSL.

### Setup del entorno

1. Tener WSL instalado con Ubuntu
2. Tener miniforge instalado en WSL:
```bash
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
```

3. Clonar el repo y ubicarse en la raíz:
```bash
git clone https://github.com/<tu-org>/pypsa-ar-base.git
cd pypsa-ar-base
```

4. Crear el entorno desde el archivo del repo:
```bash
conda env create -f environment.yml
```

5. Activar el entorno:
```bash
conda activate pypsa-earth-lock
```

6. Verificar el Python correcto:
```bash
which python
# debe mostrar: /home/<user>/miniforge3/envs/pypsa-earth-lock/bin/python
```

### Correr el pipeline 500 kV

Los scripts se ejecutan desde WSL en orden. Reemplazá `<ruta-al-repo>` con la ruta local al repo
(ej: `/mnt/c/Work/pypsa-ar-base`) y `<ruta-oficial-data>` con la ruta al directorio de datos externos
(ej: `/mnt/c/Work/pypsa-ar-sandbox/Official data`):

```bash
# Construcción de la red 500 kV
python <ruta-al-repo>/scripts/network_500kv/01_parse_raw_buses.py
python <ruta-al-repo>/scripts/network_500kv/02_parse_raw_lines.py
python <ruta-al-repo>/scripts/network_500kv/03_parse_raw_transformers.py
python <ruta-al-repo>/scripts/network_500kv/04_parse_raw_buses_sec.py
python <ruta-al-repo>/scripts/network_500kv/05_match_geosadi_coords.py
python <ruta-al-repo>/scripts/network_500kv/06_match_geosadi_geometry.py
python <ruta-al-repo>/scripts/network_500kv/07_validate_topology.py
python <ruta-al-repo>/scripts/network_500kv/07b_export_qgis.py
python <ruta-al-repo>/scripts/network_500kv/08_build_pypsa_network.py

# Mapeo de generación y demanda
python <ruta-al-repo>/scripts/network_500kv/09_map_generators.py
python <ruta-al-repo>/scripts/network_500kv/10_map_loads.py
python <ruta-al-repo>/scripts/network_500kv/10b_visualize_qgis.py
python <ruta-al-repo>/scripts/network_500kv/11_add_geo_to_generators.py
# → completar generators_pendingmanualpypsa.csv antes de continuar,
#   o usar generators_manualpypsa.csv ya versionado en data/network_500kv/
python <ruta-al-repo>/scripts/network_500kv/12_build_generators_final.py
python <ruta-al-repo>/scripts/network_500kv/12b_export_qgis_generators.py
python <ruta-al-repo>/scripts/network_500kv/12c_test_snapshot.py  # validación power flow PSS/E

# Datos reales 2024 — requieren archivos externos (no versionados en git)
python <ruta-al-repo>/scripts/network_500kv/13_clean_valores_2024.py
python <ruta-al-repo>/scripts/network_500kv/14_detectar_conflictos_generadores.py
# → completar conflictos_psse_cammesa.csv antes de continuar
python <ruta-al-repo>/scripts/network_500kv/14b_build_generators_2024.py
python <ruta-al-repo>/scripts/network_500kv/15_build_loads_2024.py
python <ruta-al-repo>/scripts/network_500kv/16_snapshot_dc_pico2024.py  # validación DC pico demanda
python <ruta-al-repo>/scripts/network_500kv/17_build_gen_profiles_2024.py

# Costos marginales — requieren archivos CVP externos (no versionados en git)
python <ruta-al-repo>/scripts/network_500kv/18_diagnostico_costos_marginales.py
# → completar columna CVP_manual en 18_costos_marginales_diagnostico.csv antes de continuar
python <ruta-al-repo>/scripts/network_500kv/18B_build_costos_marginales_2024.py

# Optimización — configurar FECHA_INICIO, FECHA_FIN y CHUNK_DIAS antes de correr
python <ruta-al-repo>/scripts/network_500kv/19_run_optimization.py

# Script 20 (análisis de resultados): pendiente de construcción
# → levantar results_2024_*.nc y comparar despacho simulado vs real CAMMESA

# Clustering espacial — configurar CLUSTER_SIZES y BUS_WEIGHTING antes de correr
python <ruta-al-repo>/scripts/network_500kv/21_network_clustering.py
```

> **Nota:** las rutas a los archivos fuente (PSS/E raw, GeoSADI, CAMMESA) están hardcodeadas en la sección
> `CONFIGURACION` al inicio de cada script. Si la estructura de carpetas es distinta, actualizarlas antes de correr.

> **Archivos externos a GitHub:** `VALORES_2024.csv`, `valores_2024_clean.csv`, `Dda_horaria_x_trafo_2024.csv`,
> `gen_profiles_2024.csv`, `CVP_Termica.csv`, `CVP_renovar.csv`, `results_2024_*.nc` y `cluster_k{N}.nc`
> no están versionados por tamaño o volumen. Ver `docs/data_sources.md` para su origen.

---

## Equipo

| Nombre | Rol |
|--------|-----|
| Gustavo Barbaran | Líder del proyecto |
| Gustavo Ramirez | Datos y modelado de red |
| Juan Manuel Bregman | Programación y pipeline |

---

## Documentación

Ver carpeta `docs/` para:
- `roadmap.md` — estado y fases del proyecto
- `architecture.md` — diseño del modelo
- `data_sources.md` — fuentes de datos y estado
- `aprendizaje_pypsaearth_ar.md` — por qué se abandonó PyPSA-Earth
- `auditoria_macro_geosadi_vs_pypsa.md` — comparación cuantitativa GeoSADI vs OSM
- `auditoria_red_oficial_vs_pypsa.md` — proceso de auditoría y decisión de migrar a GeoSADI
