"""Aggregation, validation and export of the replication-based LYBT experiment."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from . import config

VFR_ACTIVITY_STATUSES = {"AERIAL_WORK", "EN_ROUTE", "AERODROME_CIRCUIT"}
EXCLUDED_FROM_RISK_STATUSES = {"PLANNED", "CANCELLED"}
TERMINAL_STATUSES = {"LANDED", "DIVERTED", "CRASHED"}

SUMMARY_COLUMNS = [
    "weather transition at min",
    "mean generated/active count",
    "mean cancelled/not-started count",
    "P(all generated aircraft land above reserve)",
    "P(at least one aircraft ever low fuel)",
    "P(at least one aircraft ever emergency endurance)",
    "P(at least one aircraft ever below type-specific reserve)",
    "P(at least one aircraft landed below reserve)",
    "mean minimum fuel margin (% reserve)",
    "worst minimum fuel margin (% reserve)",
    "mean minimum fuel margin (% normal load)",
    "worst minimum fuel margin (% normal load)",
    "mean minimum remaining endurance (min)",
    "worst minimum remaining endurance (min)",
    "mean minimum LOW_FUEL endurance margin (min)",
    "worst minimum LOW_FUEL endurance margin (min)",
    "mean minimum EMERGENCY endurance margin (min)",
    "worst minimum EMERGENCY endurance margin (min)",
    "mean holding time among actually delayed aircraft (min)",
    "mean holding time per active aircraft (min)",
    "mean holding delay rate",
    "max holding time (min)",
    "mean total holding time (min)",
    "mean total holding fuel consumption (kg)",
    "P(at least one go-around)",
    "mean total go-around count",
    "mean sorties with at least one go-around",
    "mean go-around sortie rate",
    "mean go-around events per active sortie",
    "mean diversion rate",
    "mean diversion-before-holding rate",
    "mean diversion-after-holding rate",
    "mean number of fuel-priority landings",
    "mean landed count",
    "mean diverted count",
    "mean diverted before holding count",
    "mean diverted after holding count",
    "mean crashed count",
    "mean crashed from go-around transition count",
    "mean crashed from other status count",
    "mean crashed after go-around count",
    "mean crashed without go-around count",
    "mean not landed count",
    "mean ever VFR activity count",
    "mean ever ready-for-approach count",
    "mean ever holding count",
    "mean ever approach count",
    "mean active/unresolved count",
    "mean final simulation time (min)",
]


def _fuel_margin(sortie: Any) -> float:
    return float(
        sortie.final_fuel_kg
        - sortie.type_specific_reserve_kg
    )


def _fuel_margin_percent_of_reserve(
    sortie: Any,
) -> float:
    reserve = float(
        sortie.type_specific_reserve_kg
    )

    return (
        np.nan
        if reserve <= 0
        else (_fuel_margin(sortie) / reserve) * 100.0
    )


def _fuel_margin_percent_of_normal_load(
    sortie: Any,
) -> float:
    normal_load = float(
        sortie.normal_fuel_load_kg
    )

    return (
        np.nan
        if normal_load <= 0
        else (
            _fuel_margin(sortie)
            / normal_load
        ) * 100.0
    )


def _remaining_endurance_min(
    sortie: Any,
) -> float:
    holding_rate = float(
        sortie.fuel_consumption_holding_kg_min
    )

    return (
        np.nan
        if holding_rate <= 0
        else float(sortie.final_fuel_kg) / holding_rate
    )


def _low_fuel_endurance_margin_min(
    sortie: Any,
) -> float:
    remaining_endurance = _remaining_endurance_min(sortie)

    return (
        np.nan
        if np.isnan(remaining_endurance)
        else (
            remaining_endurance
            - config.LOW_FUEL_ENDURANCE_MIN
        )
    )


def _emergency_endurance_margin_min(
    sortie: Any,
) -> float:
    remaining_endurance = _remaining_endurance_min(sortie)

    return (
        np.nan
        if np.isnan(remaining_endurance)
        else (
            remaining_endurance
            - config.EMERGENCY_ENDURANCE_MIN
        )
    )

def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _validate_replication(
    sortie_results: list[Any],
    planned_sorties: list[Any],
    generated_active_count: int,
    excluded_count: int,
    landed_count: int,
    diverted_count: int,
    diverted_before_holding_count: int,
    diverted_after_holding_count: int,
    crashed_count: int,
) -> None:
    started_count = sum(
        bool(sortie.started)
        for sortie in planned_sorties
    )

    cancelled_count = sum(
        bool(sortie.cancelled)
        for sortie in planned_sorties
    )

    assert generated_active_count == len(sortie_results)

    assert started_count == generated_active_count, (
        "Every started sortie must have exactly one SortieResult."
    )

    assert cancelled_count == excluded_count

    assert started_count + cancelled_count == len(
        planned_sorties
    ), (
        "Every planned sortie must be either started or cancelled."
    )

    assert (
        landed_count
        + diverted_count
        + crashed_count
        == generated_active_count
    )

    assert (
        diverted_before_holding_count
        + diverted_after_holding_count
        == diverted_count
    )

    assert all(
        sortie.final_status in TERMINAL_STATUSES
        for sortie in sortie_results
    )

    assert all(
        float(sortie.final_fuel_kg) >= -1e-9
        for sortie in sortie_results
    )

    assert all(
        float(sortie.holding_fuel_consumed_kg) >= -1e-9
        for sortie in sortie_results
    )

    assert all(
        float(sortie.holding_time_sec) >= -1e-9
        for sortie in sortie_results
    )

    assert all(
        isinstance(sortie.go_around_count, (int, np.integer))
        and int(sortie.go_around_count) >= 0
        for sortie in sortie_results
    ), "go_around_count must be a non-negative integer."

    assert all(
        (
            sortie.final_status == "CRASHED"
            and sortie.crashed_from_status is not None
        )
        or (
            sortie.final_status != "CRASHED"
            and sortie.crashed_from_status is None
        )
        for sortie in sortie_results
    ), (
        "crashed_from_status must be recorded only "
        "for CRASHED sorties."
    )
    # Svaki sortie mora biti zabeležen samo jednom.
    sortie_keys = [
        (
            sortie.aircraft_type,
            sortie.aircraft_id,
            sortie.sortie_id,
        )
        for sortie in sortie_results
    ]

    assert len(sortie_keys) == len(set(sortie_keys)), (
        "Duplicate SortieResult detected."
    )

    # Vreme i gorivo u holdingu moraju se slagati.
    for sortie in sortie_results:
        expected_holding_fuel = (
            float(sortie.holding_time_sec)
            / 60.0
            * float(
                sortie.fuel_consumption_holding_kg_min
            )
        )

        assert np.isclose(
            float(sortie.holding_fuel_consumed_kg),
            expected_holding_fuel,
            rtol=1e-7,
            atol=1e-7,
        ), (
            f"Sortie {sortie.sortie_id}, "
            f"aircraft {sortie.aircraft_id} "
            f"({sortie.aircraft_type}): "
            "holding fuel/time mismatch."
        )

        if sortie.holding_time_sec > 0:
            assert sortie.entered_holding


def summarize_replication(
    aerodrome: Any,
    sortie_results: Iterable[Any],
    planned_sorties: Iterable[Any],
    transition_min: int,
    replication: int,
    seed: int,
) -> dict[str, float | int | bool | str]:
    """Create one replication-level observation for the research dataset."""
    sortie_results = list(sortie_results)
    planned_sorties = list(planned_sorties)

    simulation_end = float(
        getattr(aerodrome, "current_time", 0.0)
    )

    relevant_fleet = sortie_results

    generated_active_count = len(sortie_results)

    excluded_count = sum(
        bool(sortie.cancelled)
        for sortie in planned_sorties
    )

    reserve_pct = [_fuel_margin_percent_of_reserve(ac) for ac in relevant_fleet]
    normal_pct = [_fuel_margin_percent_of_normal_load(ac) for ac in relevant_fleet]
    remaining_endurance_min = [
        _remaining_endurance_min(ac)
        for ac in relevant_fleet
    ]

    low_fuel_endurance_margin_min = [
        _low_fuel_endurance_margin_min(ac)
        for ac in relevant_fleet
    ]

    emergency_endurance_margin_min = [
        _emergency_endurance_margin_min(ac)
        for ac in relevant_fleet
    ]
    # Holding delay means that the aircraft accumulated more than one second
    # of real waiting time in holding. Aircraft enter HOLDING only when a
    # runway is not immediately available after transition_time.
    actually_delayed = [
        ac for ac in relevant_fleet
        if float(getattr(ac, "holding_time_sec", 0.0)) > 1.0
    ]
    actual_holding_delay_count = len(actually_delayed)
    holding_times_sec = [float(ac.holding_time_sec) for ac in actually_delayed]
    total_holding_time_sec = float(
        sum(float(getattr(ac, "holding_time_sec", 0.0)) for ac in relevant_fleet)
    )

    total_go_around_count = sum(
        int(ac.go_around_count)
        for ac in relevant_fleet
    )
    go_around_sortie_count = sum(
        int(ac.go_around_count) > 0
        for ac in relevant_fleet
    )

    landed = [ac for ac in relevant_fleet if ac.final_status == "LANDED"]
    landed_count = len(landed)
    diverted_count = sum(ac.final_status == "DIVERTED" for ac in relevant_fleet)
    diverted_before_holding_count = sum(
        ac.final_status == "DIVERTED" and not ac.entered_holding for ac in relevant_fleet
    )
    diverted_after_holding_count = sum(
        ac.final_status == "DIVERTED" and ac.entered_holding for ac in relevant_fleet
    )

    crashed = [
        ac
        for ac in relevant_fleet
        if ac.final_status == "CRASHED"
    ]

    crashed_count = len(crashed)

    # Непосредно остајање без горива у MAPt–IAF прелазу.
    crashed_from_go_around_transition_count = sum(
        ac.crashed_from_status
        == "GO_AROUND_TRANSITION"
        for ac in crashed
    )

    # Остајање без горива у било ком другом статусу.
    crashed_from_other_status_count = sum(
        ac.crashed_from_status
        != "GO_AROUND_TRANSITION"
        for ac in crashed
    )

    # CRASHED после најмање једног ранијег go-around догађаја,
    # без обзира на непосредни статус.
    crashed_after_go_around_count = sum(
        int(ac.go_around_count) > 0
        for ac in crashed
    )

    # CRASHED без иједног go-around догађаја.
    crashed_without_go_around_count = sum(
        int(ac.go_around_count) == 0
        for ac in crashed
    )

    # Тачни статуси остају видљиви у replication CSV-у.
    crashed_from_statuses = "|".join(
        sorted(
            str(ac.crashed_from_status)
            for ac in crashed
        )
    )

    not_landed_count = (
        generated_active_count - landed_count
    )

    assert (
        crashed_from_go_around_transition_count
        + crashed_from_other_status_count
        == crashed_count
    )

    assert (
        crashed_after_go_around_count
        + crashed_without_go_around_count
        == crashed_count
    )

    active_unresolved_count = 0

    ever_counts = {
        "ever_vfr_activity_count": sum(
            ac.entered_vfr_activity
            for ac in relevant_fleet
        ),
        "ever_ready_for_approach_count": sum(
            ac.entered_ready_for_approach
            for ac in relevant_fleet
        ),
        "ever_holding_count": sum(
            ac.entered_holding
            for ac in relevant_fleet
        ),
        "ever_approach_count": sum(
            ac.entered_approach
            for ac in relevant_fleet
        ),
    }

    all_above_reserve = bool(relevant_fleet) and all(
        ac.final_status == "LANDED" and ac.final_fuel_kg > ac.type_specific_reserve_kg
        for ac in relevant_fleet
    )
    any_ever_low = any(ac.was_low_fuel for ac in relevant_fleet)
    any_ever_emergency = any(ac.was_emergency_endurance for ac in relevant_fleet)
    any_ever_below_reserve = any(
        ac.was_below_reserve
        for ac in relevant_fleet
    )
    any_landed_below_reserve = any(
        ac.final_status == "LANDED" and ac.final_fuel_kg <= ac.type_specific_reserve_kg
        for ac in relevant_fleet
    )

    if active_unresolved_count > 0:
        print(
            "UNRESOLVED:",
            [
                (ac.aircraft_type, ac.aircraft_id, ac.sortie_id, ac.final_status)
                for ac in relevant_fleet
                if ac.final_status not in TERMINAL_STATUSES
            ],
        )

    _validate_replication(
        sortie_results=sortie_results,
        planned_sorties=planned_sorties,
        generated_active_count=generated_active_count,
        excluded_count=excluded_count,
        landed_count=landed_count,
        diverted_count=diverted_count,
        diverted_before_holding_count=(
            diverted_before_holding_count
        ),
        diverted_after_holding_count=(
            diverted_after_holding_count
        ),
        crashed_count=crashed_count,
    )

    result: dict[str, float | int | bool | str] = {
        "transition_min": int(transition_min),
        "replication": int(replication),
        "seed": int(seed),
        "generated_active_count": int(generated_active_count),
        "cancelled_not_started_count": int(excluded_count),
        "all_aircraft_land_above_reserve": all_above_reserve,
        "at_least_one_aircraft_ever_low_fuel": any_ever_low,
        "at_least_one_aircraft_ever_emergency_endurance": any_ever_emergency,
        "at_least_one_aircraft_ever_below_reserve": any_ever_below_reserve,
        "at_least_one_aircraft_landed_below_reserve": any_landed_below_reserve,
        "minimum_fuel_margin_percent_of_reserve": float(np.nanmin(reserve_pct)) if reserve_pct else np.nan,
        "minimum_fuel_margin_percent_of_normal_load": float(np.nanmin(normal_pct)) if normal_pct else np.nan,
        "minimum_remaining_endurance_min": (
            float(np.nanmin(remaining_endurance_min))
            if remaining_endurance_min
            else np.nan
        ),

        "minimum_low_fuel_endurance_margin_min": (
            float(np.nanmin(low_fuel_endurance_margin_min))
            if low_fuel_endurance_margin_min
            else np.nan
        ),

        "minimum_emergency_endurance_margin_min": (
            float(np.nanmin(emergency_endurance_margin_min))
            if emergency_endurance_margin_min
            else np.nan
        ),
        "mean_holding_time_min": float(np.mean(holding_times_sec) / 60.0) if holding_times_sec else 0.0,
        "mean_holding_time_per_active_aircraft_min": _safe_rate(total_holding_time_sec / 60.0, generated_active_count),
        "holding_delay_rate": _safe_rate(actual_holding_delay_count, generated_active_count),
        "max_holding_time_min": float(np.max(holding_times_sec) / 60.0) if holding_times_sec else 0.0,
        "total_holding_time_min": total_holding_time_sec / 60.0,
        "total_holding_fuel_consumption_kg": float(sum(ac.holding_fuel_consumed_kg for ac in relevant_fleet)),
        "at_least_one_go_around": total_go_around_count > 0,
        "total_go_around_count": int(total_go_around_count),
        "go_around_sortie_count": int(go_around_sortie_count),
        "go_around_sortie_rate": _safe_rate(
            go_around_sortie_count,
            generated_active_count,
        ),
        "go_around_events_per_active_sortie": _safe_rate(
            total_go_around_count,
            generated_active_count,
        ),
        "diversion_rate": _safe_rate(diverted_count, generated_active_count),
        "diversion_before_holding_rate": _safe_rate(diverted_before_holding_count, generated_active_count),
        "diversion_after_holding_rate": _safe_rate(diverted_after_holding_count, generated_active_count),
        "fuel_priority_landings": int(sum(bool(ac.fuel_priority_at_landing) for ac in landed)),
        "landed_count": landed_count,
        "diverted_count": diverted_count,
        "diverted_before_holding_count": diverted_before_holding_count,
        "diverted_after_holding_count": diverted_after_holding_count,
        "crashed_count": int(crashed_count),

        "crashed_from_go_around_transition_count": int(
            crashed_from_go_around_transition_count
        ),

        "crashed_from_other_status_count": int(
            crashed_from_other_status_count
        ),

        "crashed_after_go_around_count": int(
            crashed_after_go_around_count
        ),

        "crashed_without_go_around_count": int(
            crashed_without_go_around_count
        ),

        "crashed_from_statuses": crashed_from_statuses,

        "not_landed_count": int(not_landed_count),
        **ever_counts,
        "active_unresolved_count": active_unresolved_count,
        "final_simulation_time_min": simulation_end / 60.0,
    }
    return result


def summarize_aircraft_by_type(
    sortie_results: Iterable[Any],
    planned_sorties: Iterable[Any],
    transition_min: int,
    replication: int,
    seed: int,
) -> list[dict[str, float | int | str]]:
    """
    Create one row for every aircraft type in every replication.

    Types with no active aircraft receive zero count values.
    Fuel and endurance statistics are NaN because no observation
    exists for that type in the replication.
    """
    sortie_results = list(sortie_results)
    planned_sorties = list(planned_sorties)

    # Укључујемо све типове који постоје у плану,
    # чак и ако су сви њихови sortie-ји отказани.
    all_aircraft_types = sorted({
        sortie.aircraft_type
        for sortie in planned_sorties
    })

    # SortieResult постоји само за започете и завршене летове.
    relevant = sortie_results

    rows: list[
        dict[str, float | int | str]
    ] = []

    for ac_type in all_aircraft_types:
        group = [
            ac
            for ac in relevant
            if ac.aircraft_type == ac_type
        ]

        n = len(group)

        actually_delayed_group = [
            ac
            for ac in group
            if float(
                getattr(
                    ac,
                    "holding_time_sec",
                    0.0,
                )
            ) > 1.0
        ]

        diverted = [
            ac
            for ac in group
            if ac.final_status == "DIVERTED"
        ]

        crashed_group = [
            ac
            for ac in group
            if ac.final_status == "CRASHED"
        ]

        if n == 0:
            rows.append({
                "transition_min": int(transition_min),
                "replication": int(replication),
                "seed": int(seed),
                "aircraft_type": ac_type,

                # Бројеви су нула јер у овој
                # репликацији нема активног типа.
                "active_count": 0,
                "landed_count": 0,
                "diverted_count": 0,

                "crashed_count": 0,
                "crashed_from_go_around_transition_count": 0,
                "crashed_from_other_status_count": 0,
                "crashed_after_go_around_count": 0,
                "crashed_without_go_around_count": 0,
                # Стопе и средње вредности су NaN:
                # немамо активан узорак над којим
                # би се стопа израчунала.
                "diversion_rate": np.nan,
                "diverted_before_holding_rate": np.nan,
                "diverted_after_holding_rate": np.nan,
                "holding_delay_rate": np.nan,

                "mean_holding_time_among_actually_delayed_aircraft_min": np.nan,
                "mean_holding_time_per_active_aircraft_min": np.nan,

                "at_least_one_go_around": False,
                "total_go_around_count": 0,
                "go_around_sortie_count": 0,
                "go_around_sortie_rate": np.nan,
                "go_around_events_per_active_sortie": np.nan,

                "mean_fuel_margin_percent_of_reserve": np.nan,
                "minimum_fuel_margin_percent_of_reserve": np.nan,

                "mean_fuel_margin_percent_of_normal_load": np.nan,
                "minimum_fuel_margin_percent_of_normal_load": np.nan,

                "mean_remaining_endurance_min": np.nan,
                "minimum_remaining_endurance_min": np.nan,

                "mean_low_fuel_endurance_margin_min": np.nan,
                "minimum_low_fuel_endurance_margin_min": np.nan,

                "mean_emergency_endurance_margin_min": np.nan,
                "minimum_emergency_endurance_margin_min": np.nan,

                "ever_low_fuel_rate": np.nan,
                "ever_emergency_endurance_rate": np.nan,
                "ever_below_reserve_rate": np.nan,

                "fuel_priority_landings": 0,
            })

            continue

        holding_times_delayed = [
            float(ac.holding_time_sec)
            for ac in actually_delayed_group
        ]

        reserve_margins = [
            _fuel_margin_percent_of_reserve(ac)
            for ac in group
        ]

        normal_load_margins = [
            _fuel_margin_percent_of_normal_load(ac)
            for ac in group
        ]

        remaining_endurance = [
            _remaining_endurance_min(ac)
            for ac in group
        ]

        low_fuel_endurance_margins = [
            _low_fuel_endurance_margin_min(ac)
            for ac in group
        ]

        emergency_endurance_margins = [
            _emergency_endurance_margin_min(ac)
            for ac in group
        ]

        diverted_before_holding = sum(
            not ac.entered_holding
            for ac in diverted
        )

        diverted_after_holding = sum(
            ac.entered_holding
            for ac in diverted
        )

        rows.append({
            "transition_min": int(transition_min),
            "replication": int(replication),
            "seed": int(seed),
            "aircraft_type": ac_type,

            "active_count": n,

            "landed_count": sum(
                ac.final_status == "LANDED"
                for ac in group
            ),

            "diverted_count": len(diverted),

            "crashed_count": len(crashed_group),

            "crashed_from_go_around_transition_count": sum(
                ac.crashed_from_status
                == "GO_AROUND_TRANSITION"
                for ac in crashed_group
            ),

            "crashed_from_other_status_count": sum(
                ac.crashed_from_status
                != "GO_AROUND_TRANSITION"
                for ac in crashed_group
            ),

            "crashed_after_go_around_count": sum(
                int(ac.go_around_count) > 0
                for ac in crashed_group
            ),

            "crashed_without_go_around_count": sum(
                int(ac.go_around_count) == 0
                for ac in crashed_group
            ),
            "diversion_rate": _safe_rate(
                len(diverted),
                n,
            ),

            "diverted_before_holding_rate": _safe_rate(
                diverted_before_holding,
                n,
            ),

            "diverted_after_holding_rate": _safe_rate(
                diverted_after_holding,
                n,
            ),

            "holding_delay_rate": _safe_rate(
                len(actually_delayed_group),
                n,
            ),

            "mean_holding_time_among_actually_delayed_aircraft_min": (
                float(
                    np.mean(
                        holding_times_delayed
                    )
                    / 60.0
                )
                if holding_times_delayed
                else 0.0
            ),

            "mean_holding_time_per_active_aircraft_min": (
                float(
                    sum(
                        float(ac.holding_time_sec)
                        for ac in group
                    )
                    / 60.0
                    / n
                )
            ),

            "at_least_one_go_around": any(
                int(ac.go_around_count) > 0
                for ac in group
            ),

            "total_go_around_count": sum(
                int(ac.go_around_count)
                for ac in group
            ),

            "go_around_sortie_count": sum(
                int(ac.go_around_count) > 0
                for ac in group
            ),

            "go_around_sortie_rate": _safe_rate(
                sum(
                    int(ac.go_around_count) > 0
                    for ac in group
                ),
                n,
            ),

            "go_around_events_per_active_sortie": _safe_rate(
                sum(
                    int(ac.go_around_count)
                    for ac in group
                ),
                n,
            ),

            "mean_fuel_margin_percent_of_reserve": float(
                np.nanmean(
                    reserve_margins
                )
            ),

            "minimum_fuel_margin_percent_of_reserve": float(
                np.nanmin(
                    reserve_margins
                )
            ),

            "mean_fuel_margin_percent_of_normal_load": float(
                np.nanmean(
                    normal_load_margins
                )
            ),

            "minimum_fuel_margin_percent_of_normal_load": float(
                np.nanmin(
                    normal_load_margins
                )
            ),

            "mean_remaining_endurance_min": float(
                np.nanmean(remaining_endurance)
            ),

            "minimum_remaining_endurance_min": float(
                np.nanmin(remaining_endurance)
            ),

            "mean_low_fuel_endurance_margin_min": float(
                np.nanmean(low_fuel_endurance_margins)
            ),

            "minimum_low_fuel_endurance_margin_min": float(
                np.nanmin(low_fuel_endurance_margins)
            ),

            "mean_emergency_endurance_margin_min": float(
                np.nanmean(emergency_endurance_margins)
            ),

            "minimum_emergency_endurance_margin_min": float(
                np.nanmin(emergency_endurance_margins)
            ),

            "ever_low_fuel_rate": _safe_rate(
                sum(
                    bool(ac.was_low_fuel)
                    for ac in group
                ),
                n,
            ),

            "ever_emergency_endurance_rate": _safe_rate(
                sum(
                    bool(
                        ac.was_emergency_endurance
                    )
                    for ac in group
                ),
                n,
            ),

            "ever_below_reserve_rate": _safe_rate(
                sum(
                    bool(ac.was_below_reserve)
                    for ac in group
                ),
                n,
            ),

            "fuel_priority_landings": sum(
                bool(
                    ac.fuel_priority_at_landing
                )
                for ac in group
                if ac.final_status == "LANDED"
            ),
        })

    return rows


def aggregate_replications(replication_results: pd.DataFrame) -> pd.DataFrame:
    if replication_results.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows = []
    for transition_min, g in replication_results.groupby("transition_min", sort=True):
        rows.append({
            "weather transition at min": int(transition_min),
            "mean generated/active count": g.generated_active_count.mean(),
            "mean cancelled/not-started count": g.cancelled_not_started_count.mean(),
            "P(all generated aircraft land above reserve)": g.all_aircraft_land_above_reserve.mean(),
            "P(at least one aircraft ever low fuel)": g.at_least_one_aircraft_ever_low_fuel.mean(),
            "P(at least one aircraft ever emergency endurance)": g.at_least_one_aircraft_ever_emergency_endurance.mean(),
            "P(at least one aircraft ever below type-specific reserve)":
                g.at_least_one_aircraft_ever_below_reserve.mean(),
            "P(at least one aircraft landed below reserve)": g.at_least_one_aircraft_landed_below_reserve.mean(),
            "mean minimum fuel margin (% reserve)": g.minimum_fuel_margin_percent_of_reserve.mean(),
            "worst minimum fuel margin (% reserve)": g.minimum_fuel_margin_percent_of_reserve.min(),
            "mean minimum fuel margin (% normal load)": g.minimum_fuel_margin_percent_of_normal_load.mean(),
            "worst minimum fuel margin (% normal load)": g.minimum_fuel_margin_percent_of_normal_load.min(),
            "mean minimum remaining endurance (min)":
                g.minimum_remaining_endurance_min.mean(),

            "worst minimum remaining endurance (min)":
                g.minimum_remaining_endurance_min.min(),

            "mean minimum LOW_FUEL endurance margin (min)":
                g.minimum_low_fuel_endurance_margin_min.mean(),

            "worst minimum LOW_FUEL endurance margin (min)":
                g.minimum_low_fuel_endurance_margin_min.min(),

            "mean minimum EMERGENCY endurance margin (min)":
                g.minimum_emergency_endurance_margin_min.mean(),

            "worst minimum EMERGENCY endurance margin (min)":
                g.minimum_emergency_endurance_margin_min.min(),
            "mean holding time among actually delayed aircraft (min)": g.mean_holding_time_min.mean(),
            "mean holding time per active aircraft (min)": g.mean_holding_time_per_active_aircraft_min.mean(),
            "mean holding delay rate": g.holding_delay_rate.mean(),
            "max holding time (min)": g.max_holding_time_min.max(),
            "mean total holding time (min)": g.total_holding_time_min.mean(),
            "mean total holding fuel consumption (kg)": g.total_holding_fuel_consumption_kg.mean(),
            "P(at least one go-around)": g.at_least_one_go_around.mean(),
            "mean total go-around count": g.total_go_around_count.mean(),
            "mean sorties with at least one go-around": g.go_around_sortie_count.mean(),
            "mean go-around sortie rate": g.go_around_sortie_rate.mean(),
            "mean go-around events per active sortie":
                g.go_around_events_per_active_sortie.mean(),
            "mean diversion rate": g.diversion_rate.mean(),
            "mean diversion-before-holding rate": g.diversion_before_holding_rate.mean(),
            "mean diversion-after-holding rate": g.diversion_after_holding_rate.mean(),
            "mean number of fuel-priority landings": g.fuel_priority_landings.mean(),
            "mean landed count": g.landed_count.mean(),
            "mean diverted count": g.diverted_count.mean(),
            "mean diverted before holding count": g.diverted_before_holding_count.mean(),
            "mean diverted after holding count": g.diverted_after_holding_count.mean(),
            "mean crashed count": g.crashed_count.mean(),
            "mean crashed from go-around transition count":
                g.crashed_from_go_around_transition_count.mean(),

            "mean crashed from other status count":
                g.crashed_from_other_status_count.mean(),

            "mean crashed after go-around count":
                g.crashed_after_go_around_count.mean(),

            "mean crashed without go-around count":
                g.crashed_without_go_around_count.mean(),
            "mean not landed count": g.not_landed_count.mean(),
            "mean ever VFR activity count": g.ever_vfr_activity_count.mean(),
            "mean ever ready-for-approach count": g.ever_ready_for_approach_count.mean(),
            "mean ever holding count": g.ever_holding_count.mean(),
            "mean ever approach count": g.ever_approach_count.mean(),
            "mean active/unresolved count": g.active_unresolved_count.mean(),
            "mean final simulation time (min)": g.final_simulation_time_min.mean(),
        })
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def aggregate_aircraft_types(type_replication_results: pd.DataFrame) -> pd.DataFrame:
    if type_replication_results.empty:
        return pd.DataFrame()
    keys = ["transition_min", "aircraft_type"]
    numeric = [c for c in type_replication_results.columns if c not in keys + ["replication", "seed"]]
    return type_replication_results.groupby(keys, as_index=False)[numeric].mean()

def write_experiment_outputs(
    replication_results: pd.DataFrame,
    summary: pd.DataFrame,
    type_replication_results: pd.DataFrame,
    type_summary: pd.DataFrame,
    output_dir: Path | None = None,
) -> tuple[Path, Path, Path, Path]:
    output_dir = Path(output_dir or config.RESULTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_suffix = (
        "rwy_closure"
        if config.ENABLE_RUNWAY_12L_CLOSURE
        else "baseline"
    )

    paths = (
        output_dir / f"experiment_replications_{scenario_suffix}.csv",
        output_dir / f"experiment_summary_{scenario_suffix}.csv",
        output_dir / f"aircraft_type_replications_{scenario_suffix}.csv",
        output_dir / f"aircraft_type_summary_{scenario_suffix}.csv",
    )

    for df, path in zip(
        (
            replication_results,
            summary,
            type_replication_results,
            type_summary,
        ),
        paths,
    ):
        df.to_csv(
            path,
            index=False,
            sep=";",
            decimal=",",
            encoding="utf-8-sig",
            float_format="%.4f",
        )

    return paths