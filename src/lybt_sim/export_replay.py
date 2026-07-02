# src/lybt_sim/export_replay.py
import json
from pathlib import Path

from . import config
from .trajectory import latlon_to_xy_m, generate_aircraft_trajectory
from typing import Any, Dict

def write_replay_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def export_replay_json(fleet, scenario, aip_data, out_path=None):
    ref_lat, ref_lon = config.REF_LAT, config.REF_LON

    if out_path is None:
        out_path = config.WEB_PUBLIC_DIR / "replay.json"
    else:
        out_path = Path(out_path)

    replay = {
        "meta": {
            "airport": "LYBT",
            "duration_sec": config.SIM_DURATION_SEC,
            "t_change_sec": config.T_CHANGE_SEC,
            "dt_render_sec": 1,
            "ref_lat": ref_lat,
            "ref_lon": ref_lon
        },
        "aircraft": []
    }

    for ac in fleet:
        if ac.status == "DIVERTED":
            continue
        if not getattr(ac, "landing_time", None):
            continue

        traj = generate_aircraft_trajectory(ac, scenario, aip_data)["trajectory"]

        keyframes = []
        for p in traj:
            x, y = latlon_to_xy_m(p["lat"], p["lon"], ref_lat, ref_lon)
            z = float(p["alt"]) * 0.3048  # ft -> m
            t = int(p["time"])
            keyframes.append({
                "t": t,
                "x": x,
                "y": y,
                "z": z,
                "fuel": float(getattr(ac, "current_fuel", 0)),
                "status": p.get("status", "ENROUTE")
            })

        replay["aircraft"].append({
            "id": f"AC_{ac.id:02d}",
            "type": ac.type,
            "wake": ac.wake,
            "keyframes": keyframes
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Replay snimljen: {out_path}")
    return str(out_path)
