# PyPSA-AR-BASE

Modelo reproducible de la red eléctrica argentina de alta tensión usando PyPSA.

**Estado actual:** Construcción red 500 kV — pipeline 01→07b completo, script 08 pendiente.
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

Los scripts se ejecutan desde WSL. Reemplazá `<ruta-al-repo>` con la ruta local al repo
(ej: `/mnt/c/Work/pypsa-ar-base`):

```bash
python <ruta-al-repo>/scripts/network_500kv/01_parse_raw_buses.py
python <ruta-al-repo>/scripts/network_500kv/02_parse_raw_lines.py
python <ruta-al-repo>/scripts/network_500kv/03_parse_raw_transformers.py
python <ruta-al-repo>/scripts/network_500kv/04_parse_raw_buses_sec.py
python <ruta-al-repo>/scripts/network_500kv/05_match_geosadi_coords.py
python <ruta-al-repo>/scripts/network_500kv/06_match_geosadi_geometry.py
python <ruta-al-repo>/scripts/network_500kv/07_validate_topology.py
python <ruta-al-repo>/scripts/network_500kv/07b_export_qgis.py
```

> **Nota:** las rutas a los archivos fuente (PSS/E raw, GeoSADI) están hardcodeadas en la sección
> `CONFIGURACION` al inicio de cada script. Si tu estructura de carpetas es distinta, actualizalas antes de correr.

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
