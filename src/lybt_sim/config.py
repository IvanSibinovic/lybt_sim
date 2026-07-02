# src/lybt_sim/config.py
from pathlib import Path

# Root projekta: .../lybt-sim
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
WEB_DIR = PROJECT_ROOT / "web"
WEB_PUBLIC_DIR = WEB_DIR / "public"

AIP_PROC_FILE = DATA_DIR / "aip_procedures.json"
STAR_FILE = DATA_DIR / "star_procedures.json"
LAYOUT_FILE = DATA_DIR / "aerodrome_layout.json"
ACFT_PERF_FILE = DATA_DIR / "aircraft_performance.json"
SCENARIOS_FILE = DATA_DIR / "simulation_scenarios.json"

# Sim trajanje / režim promene
SIM_DURATION_SEC = 60 * 60        # 3600
T_CHANGE_SEC     = 30 * 60        # 1800
DT_SEC           = 60             # 1 min korak

# Reference point za XY (isti kao ranije)
REF_LAT = 44.941111
REF_LON = 20.250833
