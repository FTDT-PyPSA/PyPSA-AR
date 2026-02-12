# pypsa-ar-base
Argentina  network model in PyPSA
# PyPSA-AR-BASE

Argentina electricity network model using PyPSA.

## Project Overview

This project aims to build a reproducible base model of Argentina's  transmission network using PyPSA.

The objective is to:

- Develop a clean ETL pipeline (Extract–Transform–Load)
- Structure network data (buses, lines, transformers, loads, generators)
- Reproduce a 2024 baseline network model
- Prepare the system for future scenario integration (VRE, storage, policy cases)

## Current Status

Version: v0.1  
Phase: Base model architecture and data structuring

## Project Structure (planned)

- `data/` → input datasets (not all stored in repo)
- `scripts/` → ETL and build scripts
- `config/` → model configuration files
- `docs/` → technical documentation
- `notebooks/` → exploration and testing

## Environment

Python 3.11  
PyPSA 1.0.7

## Notes

Large datasets are stored externally (Drive / shared storage).  
This repository tracks structure, scripts, and reproducible workflows.
