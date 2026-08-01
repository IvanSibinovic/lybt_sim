# Integration notes

Copy the files into the project as follows:

- `requirements.txt` -> project root
- `.gitignore` -> project root
- `run_sim.py` -> project root
- `src/lybt_sim/analysis.py` -> same path in project
- `src/lybt_sim/models.py` -> same path in project
- `src/lybt_sim/sim_engine.py` -> same path in project

Run once from the project root:

```bash
python -m pip install -r requirements.txt
python run_sim.py
```

The run writes:

- `results/transition_experiment_replications.csv` — all 5,000 observations;
- `results/transition_experiment_summary.csv` — one research row for each transition time.

## Metric conventions

- **reserve**: `minimum_fuel_emergency_kg` for the individual aircraft type;
- **all aircraft land above reserve**: every aircraft lands and has strictly more fuel than reserve after approach fuel is deducted;
- **fuel-critical**: at any point, an aircraft reaches reserve or below;
- **fuel-priority landing**: the aircraft lands with `LOW_FUEL` or `EMERGENCY` operational status;
- **not landed**: final status differs from `LANDED`.

`max holding time (min)` is the largest holding time observed among the 1,000 replications for the specified transition time. This is a sample maximum, not the mean of replication maxima.

## Confirmed corrections

1. Wake-separation JSON values are treated as seconds. No `* 60` conversion is applied.
2. Wake separation is now looked up as `leader_wake-follower_wake`, using the prior aircraft recorded on that physical runway.
3. The engine updates `aerodrome.current_time` and correctly terminates when all aircraft have a terminal status.
4. Holding fuel consumption is tracked explicitly rather than inferred later.
5. Random seed `BASE_SEED + replication` is reset for every transition time, so each five-scenario set has matched random seeds.
