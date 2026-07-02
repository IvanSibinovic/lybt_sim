# run_sim.py
import sys

sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent / "src"))

from lybt_sim.data_loader import load_all_data
from lybt_sim.sim_engine import run_all_scenarios
from lybt_sim.analysis import analyze_results
from lybt_sim.replay_recorder import ReplayRecorder
from lybt_sim.export_replay import write_replay_json
from lybt_sim import config

def main():
    # uzimamo 6 vrednosti iz data_loader.py, funkcija load_all_data
    aircraft_db, aip_data, star_data, layout_data, scenarios, rw_map = load_all_data()
    
    print("DEBUG types/keys:")
    print(" aircraft_db keys:", list(aircraft_db.keys())[:8])
    print(" aip_data keys:", list(aip_data.keys())[:8])
    print(" star_data keys:", list(star_data.keys())[:8])
    print(" layout_data keys:", list(layout_data.keys())[:8])
    print(" scenarios keys:", list(scenarios.keys())[:8])

    print("=" * 80)
    print(" NAPREDNA SIMULACIJA PRILAZA - LYBT BATAJNICA ")
    print("=" * 80)

    # rw_map debug (posle definicije)
    print("RW map example:", list(rw_map.items())[:4])

    recorder = ReplayRecorder()

    results = run_all_scenarios(
        aircraft_db=aircraft_db,
        aip_data=aip_data,
        star_data=star_data,
        layout_data=layout_data,
        scenarios=scenarios,
        analyze_fn=analyze_results,
        replay_recorder=recorder
    )
    
    print("DEBUG recorder tracks:", len(recorder.tracks))
    print("DEBUG example track keys:", list(recorder.tracks.keys())[:5])

    meta = {
        "airport": "LYBT",
        "duration_sec": config.SIM_DURATION_SEC,
        "t_change_sec": config.T_CHANGE_SEC,
        "dt_render_sec": config.DT_SEC,  # ovde ti je 60
        "ref_lat": config.REF_LAT,
        "ref_lon": config.REF_LON
    }

    payload = recorder.to_payload(meta)
    out_path = config.WEB_PUBLIC_DIR / "replay.json"
    write_replay_json(out_path, payload)

    print("Replay written:", out_path)
    print("Replay aircraft count:", len(payload["aircraft"]))


    print("\nDONE:", results)

if __name__ == "__main__":
    main()