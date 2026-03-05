# PyPSA-AR-BASE

Modelo reproducible de la red eléctrica argentina de alta tensión usando PyPSA.

**Estado actual:** Construcción red 500 kV — pipeline 01→05 completo, script 06 pendiente.  
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

El proyecto usa **WSL (Ubuntu)** para ejecutar los scripts y **Windows (Cursor o VSCODE)** para editarlos.
Esta combinación no es accidental:

- PyPSA y sus dependencias (especialmente solvers lineales) funcionan de forma más estable en Linux
- El entorno `pypsa-earth-lock` fija las versiones de todas las librerías para garantizar reproducibilidad entre máquinas del equipo
- Cursor o VSCODE en Windows permite editar cómodamente  y correr en WSL sin fricción

**No usar Python de Windows ni un venv paralelo** — los scripts asumen rutas `/mnt/c/...` y el entorno conda de WSL.

### Setup del entorno

1. Tener WSL instalado con Ubuntu
2. Tener miniforge instalado en WSL:
```bash
# Si no lo tenés:
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
```

3. Crear el entorno desde el archivo del repo:
```bash
conda env create -f /mnt/c/Work/pypsa-ar-base/environment.yml
```

4. Activar el entorno:
```bash
conda activate pypsa-earth-lock
```

5. Verificar el Python correcto:
```bash
which python
# debe mostrar: /home/<user>/miniforge3/envs/pypsa-earth-lock/bin/python
```

### Correr el pipeline 500 kV

```bash
python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/01_parse_raw_buses.py
python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/02_parse_raw_lines.py
python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/03_match_geosadi_coords.py
python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/04_match_geosadi_geometry.py
python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/05_validate_topology.py
python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/05b_export_qgis.py  
```


---

## Equipo

| Nombre | Rol |
|--------|-----|
| Gustavo Barbaran | Líder del proyecto |
| Gus | Datos y modelado de red |
| Juan | Programación y pipeline |

---

## Documentación

Ver carpeta `docs/` para:
- `roadmap.md` — estado y fases del proyecto
- `architecture.md` — diseño del modelo
- `data_sources.md` — fuentes de datos y estado
- `aprendizaje_pypsaearth_ar.md` — por qué se abandonó PyPSA-Earth
- `auditoria_macro_geosadi_vs_pypsa.md` — comparación cuantitativa GeoSADI vs OSM
- `auditoria_red_oficial_vs_pypsa.md` — proceso de auditoría y decisión de migrar a GeoSADI
