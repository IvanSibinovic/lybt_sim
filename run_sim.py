"""Run the paired 5 × 1,000-replication VFR→IFR transition experiment."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(str(Path(__file__).resolve().parent / "src"))

from lybt_sim.analysis import (
    aggregate_aircraft_types,
    aggregate_replications,
    summarize_aircraft_by_type,
    summarize_replication,
    write_experiment_outputs,
)
from lybt_sim.data_loader import load_all_data
from lybt_sim.sim_engine import (
    build_transition_scenario,
    resolve_weather_minima,
    run_simulation,
)

TRANSITION_MINUTES = (30, 45, 60, 75, 90)
# N_REPLICATIONS treba da bude 1000; manji broj koristiti samo za brzo testiranje.
N_REPLICATIONS = 1000
BASE_SEED = 20_260_707


def select_vfr_base_scenario(scenarios: dict) -> dict:
    base_scenario = next(
        (
            sc for sc in scenarios["scenarios"]
            if sc.get("parameters", {}).get("weather_conditions") == "VFR"
        ),
        None,
    )
    if base_scenario is None:
        raise ValueError("No VFR base scenario was found in simulation_scenarios.json.")
    return base_scenario


def main() -> None:
    aircraft_db, aip_procedures, star_data, layout_data, scenarios, _rw_map, common_fpl = load_all_data()
    vfr_minima, ifr_minima = resolve_weather_minima(scenarios)
    base_scenario = select_vfr_base_scenario(scenarios)

    records: list[dict] = []
    type_records: list[dict] = []
    total_runs = len(TRANSITION_MINUTES) * N_REPLICATIONS
    completed = 0

    # Common random numbers / matched random seeds:
    # replication r uses BASE_SEED + r under every transition time.
    for replication in range(1, N_REPLICATIONS + 1):
        seed = BASE_SEED + replication
        for transition_min in TRANSITION_MINUTES:
            np.random.seed(seed)
            scenario = build_transition_scenario(base_scenario, transition_min)
            aerodrome, fleet, sortie_results, planned_sorties = run_simulation(
                scenario=scenario,
                aircraft_db=aircraft_db,
                layout_data=layout_data,
                star_data=star_data,
                common_fpl=common_fpl,
                vfr_minima=vfr_minima,
                ifr_minima=ifr_minima,
                approach_rules=(aip_procedures["approach_sequencing"]),
                verbose=False,
            )
            records.append(
                summarize_replication(
                    aerodrome=aerodrome,
                    sortie_results=sortie_results,
                    planned_sorties=planned_sorties,
                    transition_min=transition_min,
                    replication=replication,
                    seed=seed,
                )
            )

            type_records.extend(
                summarize_aircraft_by_type(
                    sortie_results=sortie_results,
                    planned_sorties=planned_sorties,
                    transition_min=transition_min,
                    replication=replication,
                    seed=seed,
                )
            )
            completed += 1

        if replication % 100 == 0:
            print(f"Completed {completed}/{total_runs} runs ({replication}/{N_REPLICATIONS} replications).")

    replication_results = pd.DataFrame(records)
    type_replication_results = pd.DataFrame(type_records)
    summary = aggregate_replications(replication_results)
    type_summary = aggregate_aircraft_types(type_replication_results)
    (
        replication_path,
        summary_path,
        type_replication_path,
        type_summary_path,
    ) = write_experiment_outputs(
        replication_results,
        summary,
        type_replication_results,
        type_summary,
    )

    print("\nResearch table:")
    print(summary.to_string(index=False))
    print(f"\nReplication-level data: {replication_path}")
    print(f"Summary table: {summary_path}")
    print(f"Aircraft-type replication data: {type_replication_path}")
    print(f"Aircraft-type summary: {type_summary_path}")


if __name__ == "__main__":
    main()