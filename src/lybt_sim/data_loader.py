# src/lybt_sim/data_loader.py
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from . import config

def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def build_runway_end_to_physical_map(layout: Dict[str, Any]) -> Dict[str, str]:
    """
    layout runway identifiers su dati u formatu: "12R/30L".
    Vraća mapu: {"12R": "12R/30L", "30L": "12R/30L", ...}
    """
    mapping: Dict[str, str] = {}
    for rw in layout.get("runways", []):
        rid = rw.get("identifier", "")
        if "/" in rid:
            a, b = rid.split("/", 1)
            mapping[a.strip()] = rid
            mapping[b.strip()] = rid
        else:
            # ako je već single-end, mapiraj na sebe
            mapping[rid.strip()] = rid.strip()
    return mapping

def load_all_data():
    aircraft_data = load_json(config.ACFT_PERF_FILE)
    aip_data      = load_json(config.AIP_PROC_FILE)
    star_data     = load_json(config.STAR_FILE)
    layout_data   = load_json(config.LAYOUT_FILE)
    scenarios     = load_json(config.SCENARIOS_FILE)
    common_fpl   = load_json(config.COMMON_FPL_FILE)

    # runway end -> runway pair map (12L -> 12L/30R)
    rw_map = {}
    for rwy in layout_data.get("runways", []):
        ident = rwy.get("identifier", "")
        if "/" in ident:
            a, b = ident.split("/", 1)
            rw_map[a.strip()] = ident
            rw_map[b.strip()] = ident

    return aircraft_data, aip_data, star_data, layout_data, scenarios, rw_map, common_fpl
