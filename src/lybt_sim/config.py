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
COMMON_FPL_FILE = DATA_DIR / "common_fpl.json"

# Sim trajanje / režim promene
SIM_DURATION_SEC = 120 * 60       		# 7200
DT_SEC           = 5              		# 5 sec korak
POST_TRANSITION_SAFETY_SEC = 180 * 60	# moguće trajanje simulacije nakon promene uslova na IFR (zastitni sloj da ne bi while petlja isla u beskonacnost)


# Stohastička odstupanja od nominalnog common FPL plana.
TAKEOFF_JITTER_MIN = 15.0
TAKEOFF_JITTER_LIMIT_MIN = 25.0
ACTIVITY_DURATION_FACTOR_MIN = 0.95
ACTIVITY_DURATION_FACTOR_MODE = 1.00
ACTIVITY_DURATION_FACTOR_MAX = 1.05
MIGRATION_JITTER_MIN = 2.0
RETURN_JITTER_MIN = 2.0

#Preostalo vreme leta u minutima koje aktivira promenu statusa:
LOW_FUEL_ENDURANCE_MIN = 25.0
EMERGENCY_ENDURANCE_MIN = 15.0

# vreme koje vazduhoplov u holdingu mora da saceka zbog vazduhoplova koji je produzio na go around po mapt
GO_AROUND_HOLDING_RELEASE_FRACTION = 1.0 / 3.0

# Primarna PSS za sletanje.
# U aerodrome_layout.json identifikator fizičke PSS je "12L/30R".
LANDING_RUNWAY_ID = "12L/30R"

# Alternativna PSS. U IFR uslovima mogu je koristiti samo
# vazduhoplovi sa RNP sposobnošću.
ALTERNATE_LANDING_RUNWAY_ID = "12R/30L"

# Scenario analize osetljivosti:
# False = nema zatvaranja 12L;
# True  = 12L se privremeno zatvara.
ENABLE_RUNWAY_12L_CLOSURE = True

# Zatvaranje počinje 10 minuta nakon pojave IFR uslova.
RUNWAY_12L_CLOSURE_DELAY_SEC = 10 * 60

# PSS 12L ostaje zatvorena 15 minuta.
RUNWAY_12L_CLOSURE_DURATION_SEC = 15 * 60

#vreme od završetka procedure do dodira
IFR_TOUCHDOWN_EXTRA_TIME_SEC = 5.0

# Reference point za XY (isti kao ranije)
REF_LAT = 44.941111
REF_LON = 20.250833
