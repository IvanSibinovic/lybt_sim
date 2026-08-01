from __future__ import annotations

import copy
from typing import Any

import numpy as np

from . import config
from .models import (
    Aircraft,
    Aerodrome,
    PlannedSortie,
    SortieResult,
)

TERMINAL_STATUSES = {"LANDED", "DIVERTED", "CRASHED", "CANCELLED"}
VFR_ACTIVITY_STATUSES = {"AERIAL_WORK", "EN_ROUTE", "AERODROME_CIRCUIT"}

def _sample_takeoff_time_sec(
    nominal_time_min: float,
) -> float:
    """
    Generiše željeno vreme poletanja pomoću ograničene
    Gaussian + Exponential raspodele.
    (exponentially modified Gaussian - EMG)

    TAKEOFF_JITTER_MIN određuje intenzitet odstupanja,
    dok TAKEOFF_JITTER_LIMIT_MIN predstavlja čvrstu
    granicu odstupanja od nominalnog vremena.
    """

    nominal_time_min = float(nominal_time_min)
    takeoff_jitter_min = float(
        config.TAKEOFF_JITTER_MIN
    )
    jitter_limit_min = float(
        config.TAKEOFF_JITTER_LIMIT_MIN
    )

    if nominal_time_min < 0.0:
        raise ValueError(
            "Nominal takeoff time cannot be negative."
        )

    if takeoff_jitter_min < 0.0:
        raise ValueError(
            "TAKEOFF_JITTER_MIN cannot be negative."
        )

    if jitter_limit_min < 0.0:
        raise ValueError(
            "TAKEOFF_JITTER_LIMIT_MIN cannot be negative."
        )

    if takeoff_jitter_min == 0.0:
        return nominal_time_min * 60.0

    if nominal_time_min == 0.0:
        # Prvi planirani let ne može poleteti pre početka
        # simulacije, pa dobija samo pozitivno kašnjenje.
        while True:
            deviation_min = np.random.exponential(
                scale=takeoff_jitter_min / 2.0
            )

            if deviation_min <= jitter_limit_min:
                break
    else:
        # Gaussian deo omogućava ranije ili kasnije
        # poletanje, a exponential deo stvara asimetriju
        # prema kašnjenju.
        while True:
            gaussian_noise = np.random.normal(
                loc=0.0,
                scale=takeoff_jitter_min / 3.0,
            )

            exponential_delay = np.random.exponential(
                scale=takeoff_jitter_min / 3.0,
            )

            deviation_min = (
                gaussian_noise + exponential_delay
            )

            if (
                -jitter_limit_min
                <= deviation_min
                <= jitter_limit_min
            ):
                break

    sampled_time_min = max(
        0.0,
        nominal_time_min + deviation_min,
    )

    return float(sampled_time_min) * 60.0


def _sample_activity_duration_sec(
    nominal_duration_min: float,
) -> float:

    factor = np.random.triangular(
        config.ACTIVITY_DURATION_FACTOR_MIN,
        config.ACTIVITY_DURATION_FACTOR_MODE,
        config.ACTIVITY_DURATION_FACTOR_MAX,
    )

    return max(
        0.0,
        float(nominal_duration_min) * float(factor) * 60.0,
    )


def _sample_duration_around_nominal_sec(
    nominal_time_min: float,
    jitter_min: float,
) -> float:
    """Sample a non-negative duration around its nominal value."""

    nominal_time_min = float(nominal_time_min)

    # Nulto migration/return vreme ostaje nula,
    # npr. kod aerodromskog Å¡kolskog kruga.
    if nominal_time_min <= 0.0:
        return 0.0

    sampled_time_min = np.random.triangular(
        max(0.0, nominal_time_min - float(jitter_min)),
        nominal_time_min,
        nominal_time_min + float(jitter_min),
    )

    return float(sampled_time_min) * 60.0


def create_flight_plan(
    common_fpl: dict[str, Any],
    aircraft_db: dict[str, Any],
) -> tuple[dict[tuple[str, int], Aircraft], list[PlannedSortie]]:
    """
    Formira fiziÄke vazduhoplove i njihove planirane letove
    na osnovu common_fpl.json.
    """

    performance_by_type = {
        ac["aircraft_type"]: ac
        for ac in aircraft_db["aircraft_data"]
    }

    aircraft_registry: dict[tuple[str, int], Aircraft] = {}
    planned_sorties: list[PlannedSortie] = []

    for aircraft_type, aircraft_list in common_fpl["aircraft_types"].items():

        if aircraft_type not in performance_by_type:
            raise KeyError(
                f"Aircraft type '{aircraft_type}' is missing "
                "from aircraft_performance.json"
            )

        performance_data = performance_by_type[aircraft_type]

        for aircraft_data in aircraft_list:
            aircraft_id = int(aircraft_data["aircraft_id"])
            aircraft_key = (aircraft_type, aircraft_id)

            if aircraft_key in aircraft_registry:
                raise ValueError(
                    f"Duplicate aircraft: {aircraft_key}"
                )

            aircraft_registry[aircraft_key] = Aircraft(
                ac_id=aircraft_id,
                ac_type=aircraft_type,
                performance_data=performance_data,
            )

            for sortie_data in aircraft_data["sorties"]:
                nominal_takeoff_time_sec = (
                    float(sortie_data["takeoff_time_min"]) * 60.0
                )

                nominal_activity_duration_sec = (
                    float(sortie_data["activity_duration_min"]) * 60.0
                )

                nominal_migration_time_sec = (
                    float(sortie_data["migration_time_min"]) * 60.0
                )

                nominal_sortie_return_time_sec = (
                    float(sortie_data["sortie_return_time_min"]) * 60.0
                )

                planned_sorties.append(
                    PlannedSortie(
                        aircraft_type=aircraft_type,
                        aircraft_id=aircraft_id,
                        sortie_id=int(sortie_data["sortie_id"]),
                        refuelled=bool(sortie_data["refuelled"]),

                        nominal_takeoff_time_sec=(
                            nominal_takeoff_time_sec
                        ),
                        nominal_activity_duration_sec=(
                            nominal_activity_duration_sec
                        ),
                        nominal_migration_time_sec=(
                            nominal_migration_time_sec
                        ),
                        nominal_sortie_return_time_sec=(
                            nominal_sortie_return_time_sec
                        ),

                        takeoff_time_sec=_sample_takeoff_time_sec(
                            sortie_data["takeoff_time_min"]
                        ),

                        activity_duration_sec=(
                            _sample_activity_duration_sec(
                                sortie_data["activity_duration_min"]
                            )
                        ),

                        activity_type=str(
                            sortie_data["designation"]
                        ),

                        migration_time_sec=(
                            _sample_duration_around_nominal_sec(
                                sortie_data["migration_time_min"],
                                config.MIGRATION_JITTER_MIN,
                            )
                        ),

                        sortie_return_time_sec=(
                            _sample_duration_around_nominal_sec(
                                sortie_data["sortie_return_time_min"],
                                config.RETURN_JITTER_MIN,
                            )
                        ),
                    )
                )

    planned_sorties.sort(
        key=lambda sortie: sortie.takeoff_time_sec
    )

    return aircraft_registry, planned_sorties

def _consume_until_event(aircraft: Aircraft, simulation_time: int, event_time: float, mode: str) -> None:
    """Burn only the part of the one-minute step that occurs before an event."""
    burn_seconds = min(config.DT_SEC, max(0.0, event_time - simulation_time))
    if burn_seconds > 0:
        aircraft.consume_fuel(burn_seconds, mode=mode)


def _enter_holding(aircraft: Aircraft, start_time: float) -> None:
    """Place aircraft in HOLDING and initialize exact holding accounting."""
    aircraft.entered_holding = True
    aircraft.status = "HOLDING"
    aircraft.waiting_start = float(start_time)
    aircraft.holding_start = float(start_time)
    aircraft.holding_end_time = None
    aircraft.holding_last_update_time = float(start_time)


def _account_holding_until(aircraft: Aircraft, event_time: float) -> None:
    """Burn fuel for the exact elapsed time spent in holding up to event_time."""
    if aircraft.status != "HOLDING" or aircraft.holding_start is None:
        return
    last_time = (
        aircraft.holding_last_update_time
        if aircraft.holding_last_update_time is not None
        else aircraft.holding_start
    )
    elapsed = max(0.0, float(event_time) - float(last_time))
    if elapsed > 0:
        aircraft.consume_fuel(elapsed, mode="HOLDING")
        aircraft.holding_time_sec += elapsed
        aircraft.holding_last_update_time = float(event_time)


def _close_holding(aircraft: Aircraft, end_time: float) -> None:
    """Close exact holding accounting when aircraft leaves holding."""
    if aircraft.holding_start is None or aircraft.holding_end_time is not None:
        return
    _account_holding_until(aircraft, end_time)
    aircraft.holding_end_time = float(end_time)


def _set_terminal_status(aircraft: Aircraft, status: str, event_time: float) -> None:
    """Set a terminal state and close holding if necessary."""
    if aircraft.status == "HOLDING":
        _close_holding(aircraft, event_time)
    aircraft.terminal_time = float(event_time)
    aircraft.status = status

def _select_landing_runway(
    aerodrome: Aerodrome,
    aircraft: Aircraft,
    use_instrument: bool,
    simulation_time: float,
) -> tuple[str, str] | None:
    """
    Bira raspoloživu PSS i prag za konkretan vazduhoplov.

    Prioritet uvek ima 12L. PSS 12R koristi se samo:
    - dok je 12L zatvorena;
    - u IFR uslovima;
    - ako vazduhoplov ima RNP sposobnost.
    """

    primary_runway_id = config.LANDING_RUNWAY_ID

    if aerodrome.is_runway_open(
        primary_runway_id,
        simulation_time,
    ):
        return primary_runway_id, "12L"

    alternate_runway_id = (
        config.ALTERNATE_LANDING_RUNWAY_ID
    )

    if (
        use_instrument
        and aircraft.rnp_approach_ability
        and aerodrome.is_runway_open(
            alternate_runway_id,
            simulation_time,
        )
    ):
        return alternate_runway_id, "12R"

    return None

def _select_ifr_queue_leader(
    fleet: list[Aircraft],
    aerodrome: Aerodrome,
    simulation_time: float,
) -> Aircraft | None:
    """
    Vraća vazduhoplov koji sledeći sme da pokuša IFR prilaz.

    U red ulaze samo vazduhoplovi za koje u datom trenutku
    postoji raspoloživa PSS.

    Redosled je:
      1. veći operativni prioritet;
      2. raniji dolazak u red za prilaz;
      3. stabilan identifikacioni redosled.
    """

    candidates = [
        aircraft
        for aircraft in fleet
        if (
            aircraft.status
            in {
                "READY_FOR_APPROACH",
                "HOLDING",
            }
            and _select_landing_runway(
                aerodrome=aerodrome,
                aircraft=aircraft,
                use_instrument=True,
                simulation_time=simulation_time,
            )
            is not None
        )
    ]

    if not candidates:
        return None

    def queue_key(aircraft: Aircraft) -> tuple:
        queue_entry_time = aircraft.ready_for_approach_time

        if queue_entry_time is None:
            queue_entry_time = aircraft.waiting_start

        if queue_entry_time is None:
            queue_entry_time = float("inf")

        return (
            -float(aircraft.priority),
            float(queue_entry_time),
            str(aircraft.type),
            int(aircraft.id),
            int(aircraft.sortie_id or 0),
        )

    return min(candidates, key=queue_key)

def _divert_aircraft(
    aircraft: Aircraft,
    simulation_time: float,
    reason: str,
    log,
    record_sortie_result,
) -> None:

    aircraft.diverted_from_status = aircraft.status

    _set_terminal_status(
        aircraft,
        "DIVERTED",
        simulation_time,
    )

    record_sortie_result(aircraft)

    log(
        f"[{simulation_time / 60:.2f} min] "
        f"DIVERTED: aircraft {aircraft.id} "
        f"({aircraft.type}); reason={reason}; "
        f"fuel={aircraft.current_fuel:.1f} kg; "
        f"reserve={aircraft.type_specific_fuel_reserve:.1f} kg"
    )

def _try_clear_for_approach(
    aerodrome: Aerodrome,
    aircraft: Aircraft,
    use_instrument: bool,
    separation_minima: dict[str, float],
    simulation_time: int,
    from_holding: bool,
    log,
    record_sortie_result,
) -> bool:
    """
    Pokusava da odobri vazduhoplovu prilaz na PSS 12L.

    U IFR uslovima samo jedan vazduhoplov može koristiti modelovanu
    proceduru prilaza u datom trenutku. Sledeci vazduhoplov moze
    zapoceti prilaz kada prethodni dostigne planirano vreme dodira PSS.

    IFR trajanje prilaza:
        instrument_approach_time_min + 5 sekundi

    Povratna vrednost:
        True  - vazduhoplov je usao u prilaz ili je preusmeren;
        False - prilaz trenutno nije dostupan.
    """

    # Dodela approach procedure, ako jos nije dodeljena.
    if aircraft.assigned_star is None:
        aircraft.assigned_star = aerodrome.assign_star_route(
            aircraft
        )

    # Faktor se izvlaci samo jednom za konkretan pokusaj prilaza.
    # Sacuvana vrednost ostaje ista dok vazduhoplov ceka odobrenje.
    if (
        aircraft.realized_approach_duration_sec is None
        or aircraft.realized_approach_is_instrument
        != use_instrument
    ):
        approach_factor = float(
            np.random.triangular(1.00, 1.10, 1.30)
        )

        if use_instrument:
            aircraft.realized_approach_duration_sec = (
                float(aircraft.instrument_time) * approach_factor
                + float(config.IFR_TOUCHDOWN_EXTRA_TIME_SEC)
            )
        else:
            aircraft.realized_approach_duration_sec = (
                float(aircraft.visual_time) * approach_factor
            )

        aircraft.realized_approach_is_instrument = use_instrument

    approach_duration = float(
        aircraft.realized_approach_duration_sec
    )

    # Gorivo potrebno samo za završetak prilaza.
    required_approach_fuel = (
        float(aircraft.fuel_consumption_approach)
        * approach_duration
        / 60.0
    )

    # Ako nema dovoljno goriva ni za sam prilaz,
    # vazduhoplov se odmah preusmerava.
    if aircraft.current_fuel < required_approach_fuel:
        _divert_aircraft(
            aircraft=aircraft,
            simulation_time=simulation_time,
            reason="insufficient fuel to complete approach",
            log=log,
            record_sortie_result=record_sortie_result,
        )
        return True

    # Planirano vreme dodira PSS mora biti poznato pre izbora PSS
    # Prilaz ne sme biti odobren ako bi sletanje 
    # palo u interval njenog privremenog zatvaranja.
    planned_landing_time = (
        float(simulation_time)
        + approach_duration
    )

    # Izbor PSS koja će biti raspoloživa u planiranom
    # trenutku sletanja.
    runway_selection = _select_landing_runway(
        aerodrome=aerodrome,
        aircraft=aircraft,
        use_instrument=use_instrument,
        simulation_time=planned_landing_time,
    )

    if runway_selection is None:
        return False

    runway_id, landing_end = runway_selection

    runway_data = aerodrome.runways.get(runway_id)

    if runway_data is None:
        raise KeyError(
            f"Landing runway '{runway_id}' "
            "is missing from aerodrome layout."
        )

    # Provera raspoložive dužine izabranog pravca sletanja.
    can_land_physically, _ = aircraft.can_land_on_runway(
        runway_data,
        weather="DRY",
        landing_end=landing_end,
    )

    if not can_land_physically:
        return False

    # vazduhoplov koji je vec u APPROACH nije predmet provere! (nastavlja prilaz)
    # provera se aktivira samo kada algoritam ponovo pokusa da dodeli prilaz vazudhoplovu u holdingu
    go_around_blocks_holding = (
        use_instrument
        and from_holding
        and (
            aerodrome.go_around_holding_block_start_sec
            <= simulation_time
            < aerodrome.go_around_holding_release_time_sec
        )
    )

    if go_around_blocks_holding:
        return False
    # Provera da li je procedura prilaza trenutno slobodna.
    procedure_available, _ = aerodrome.can_land(
        aircraft=aircraft,
        runway_id=runway_id,
        approach_start_time=simulation_time,
        approach_duration_sec=approach_duration,
        use_instrument=use_instrument,
    )

    if not procedure_available:
        return False

    # Ako vazduhoplov izlazi iz holdinga,
    # zatvaramo obračun vremena i potrošnje u holdingu.
    if from_holding:
        _close_holding(
            aircraft,
            simulation_time,
        )

    # Vazduhoplov ulazi u prilaz.
    aircraft.entered_approach = True
    aircraft.status = "APPROACH"
    aircraft.assigned_runway = runway_id
    aircraft.approach_start = float(simulation_time)
    aircraft.landing_time = planned_landing_time

    if use_instrument:
        aerodrome.register_approach(
            aircraft=aircraft,
            approach_start_time=simulation_time,
            landing_time=planned_landing_time,
        )

    # busy_until sada samo beleži zauzetost PSS nakon dodira.
    # Ne koristi se za određivanje početka sledećeg prilaza.
    runway_data["busy_until"] = (
        planned_landing_time
        + float(aircraft.rot)
    )

    log(
        f"[{simulation_time / 60:.2f} min] "
        f"APPROACH: aircraft {aircraft.id} "
        f"({aircraft.type}); "
        f"landing at {planned_landing_time / 60:.2f} min; "
        f"approach duration={approach_duration / 60:.2f} min; "
        f"runway={runway_id}; "
        f"fuel={aircraft.current_fuel:.1f} kg"
    )

    return True


def run_simulation(
    scenario: dict[str, Any],
    aircraft_db: dict[str, Any],
    layout_data: dict[str, Any],
    star_data: dict[str, Any],
    common_fpl: dict[str, Any],
    vfr_minima: dict[str, float],
    ifr_minima: dict[str, float],
    approach_rules: dict[str, Any],
    replay_recorder=None,
    verbose: bool = False,
):

    aerodrome = Aerodrome(
        layout_data=layout_data,
        star_data=star_data,
        approach_rules=approach_rules,
    )

    aircraft_registry, planned_sorties = create_flight_plan(
        common_fpl=common_fpl,
        aircraft_db=aircraft_db,
    )

    fleet = list(aircraft_registry.values())

    sortie_results: list[SortieResult] = []

    base_weather = scenario["parameters"]["weather_conditions"]
    transition = scenario["parameters"].get("weather_transition")

    transition_time_sec = (
        int(float(transition["at_min"]) * 60.0)
        if transition
        else None
    )

    # Određivanje trenutka pojave IFR uslova.
    if (
        transition is not None
        and str(transition.get("to", "")).upper() == "IFR"
    ):
        ifr_start_time_sec = transition_time_sec
    elif str(base_weather).upper() == "IFR":
        # Za scenario koji od početka ima IFR uslove.
        ifr_start_time_sec = 0
    else:
        ifr_start_time_sec = None

    aerodrome.configure_runway_12l_closure(
        ifr_start_time_sec=ifr_start_time_sec,
    )

    simulation_time = 0

    #mapa planova:
    sortie_by_key = {
        (
            sortie.aircraft_type,
            sortie.aircraft_id,
            sortie.sortie_id,
        ): sortie
        for sortie in planned_sorties
    }
    # Nakon promene vremena simulacija se nastavlja dok se
    # svi vazduhoplovi koji su poleteli ne razreše.
    if transition_time_sec is not None:
        max_simulation_time = (
            transition_time_sec
            + int(
                getattr(
                    config,
                    "POST_TRANSITION_SAFETY_SEC",
                    120 * 60,
                )
            )
        )
    else:
        max_simulation_time = int(
            getattr(
                config,
                "SIM_DURATION_SEC",
                60 * 60,
            )
        )

    def log(message: str) -> None:
        if verbose:
            print(message)

    if (
        aerodrome.runway_12l_closure_start_sec is not None
        and aerodrome.runway_12l_closure_end_sec is not None
    ):
        log(
            "RUNWAY CLOSURE: "
            f"{config.LANDING_RUNWAY_ID} closed from "
            f"{aerodrome.runway_12l_closure_start_sec / 60:.2f} "
            f"to "
            f"{aerodrome.runway_12l_closure_end_sec / 60:.2f} min"
        )

    recorded_sorties: set[tuple[str, int, int]] = set()

    def cancel_future_sorties(
        aircraft: Aircraft,
        cause_status: str,
    ) -> None:
        """
        Otkazuje sve kasnije nezapocete sortie-je istog fizickog
        vazduhoplova nakon DIVERTED ili CRASHED ishoda.
        """

        if aircraft.sortie_id is None:
            return

        for sortie in planned_sorties:
            same_aircraft = (
                sortie.aircraft_type == aircraft.type
                and sortie.aircraft_id == aircraft.id
            )

            is_later_sortie = (
                sortie.sortie_id > aircraft.sortie_id
            )

            if (
                same_aircraft
                and is_later_sortie
                and not sortie.started
                and not sortie.cancelled
            ):
                sortie.cancelled = True
                sortie.status = (
                    "CANCELLED_AIRCRAFT_UNAVAILABLE"
                )

                log(
                    f"[{simulation_time / 60:.2f} min] "
                    f"SORTIE CANCELLED: aircraft "
                    f"{sortie.aircraft_id} "
                    f"({sortie.aircraft_type}), "
                    f"sortie {sortie.sortie_id}; "
                    f"reason=aircraft unavailable after "
                    f"{cause_status}"
                )
    def record_sortie_result(
        aircraft: Aircraft,
    ) -> None:
        """Sačuvaj konačan rezultat jednog sortie-ja."""

        if aircraft.sortie_id is None:
            return

        key = (
            aircraft.type,
            aircraft.id,
            aircraft.sortie_id,
        )

        # Sprečava dvostruko beleženje istog sortie-ja.
        if key in recorded_sorties:
            return

        sortie_results.append(
            SortieResult(
                aircraft_type=aircraft.type,
                aircraft_id=int(aircraft.id),
                sortie_id=int(aircraft.sortie_id),

                final_status=str(aircraft.status),

                takeoff_time_sec=float(aircraft.takeoff_time),
                terminal_time_sec=(
                    float(aircraft.terminal_time)
                    if aircraft.terminal_time is not None
                    else None
                ),

                initial_fuel_kg=float(
                    aircraft.sortie_initial_fuel_kg
                ),
                final_fuel_kg=float(
                    aircraft.current_fuel
                ),
                type_specific_reserve_kg=float(
                    aircraft.type_specific_fuel_reserve
                ),
                normal_fuel_load_kg=float(
                    aircraft.normal_fuel_load
                ),
                fuel_consumption_holding_kg_min=float(
                    aircraft.fuel_consumption_holding
                ),
                holding_time_sec=float(
                    aircraft.holding_time_sec
                ),
                holding_fuel_consumed_kg=float(
                    aircraft.holding_fuel_consumed
                ),
                entered_holding=bool(
                    aircraft.entered_holding
                ),
                entered_approach=bool(
                    aircraft.entered_approach
                ),
                entered_vfr_activity=bool(
                    aircraft.entered_vfr_activity
                ),
                entered_ready_for_approach=bool(
                    aircraft.entered_ready_for_approach
                ),
                was_low_fuel=bool(
                    aircraft.was_low_fuel
                ),
                was_emergency_endurance=bool(
                    aircraft.was_emergency_endurance
                ),
                was_below_reserve=bool(
                    aircraft.was_below_reserve
                ),
                fuel_priority_at_landing=bool(
                    aircraft.fuel_priority_at_landing
                ),
                go_around_count=int(
                    aircraft.go_around_count
                ),
                crashed_from_status=(
                    str(aircraft.crashed_from_status)
                    if aircraft.crashed_from_status is not None
                    else None
                ),
            )
        )

        planned_sortie = sortie_by_key.get(key)
        if planned_sortie is not None:
            planned_sortie.completed = True
            planned_sortie.status = str(aircraft.status)

        if aircraft.status in {
            "DIVERTED",
            "CRASHED",
        }:
            cancel_future_sorties(
                aircraft=aircraft,
                cause_status=str(aircraft.status),
            )

        recorded_sorties.add(key)

    def current_rules(
        sim_time_sec: int,
    ) -> tuple[bool, dict[str, float]]:
        weather_now = base_weather

        if (
            transition_time_sec is not None
            and sim_time_sec >= transition_time_sec
        ):
            weather_now = transition["to"]

        if weather_now == "IFR":
            return True, ifr_minima

        return False, vfr_minima

    def unresolved_exists() -> bool:
        active_aircraft_exists = any(
            aircraft.status not in TERMINAL_STATUSES
            for aircraft in fleet
        )

        future_sortie_exists = any(
            not sortie.started
            and not sortie.cancelled
            and (
                transition_time_sec is None
                or simulation_time < transition_time_sec
            )
            for sortie in planned_sorties
        )

        return active_aircraft_exists or future_sortie_exists

    while unresolved_exists():
        if simulation_time >= max_simulation_time:
            unresolved = [
                (
                    ac.type,
                    ac.id,
                    ac.sortie_id,
                    ac.status,
                    ac.landing_time,
                )
                for ac in fleet
                if ac.status not in TERMINAL_STATUSES
            ]

            raise RuntimeError(
                f"Simulation safety limit reached. "
                f"Unresolved aircraft: {unresolved}"
            )

        aerodrome.current_time = simulation_time

        use_instrument, separation_minima = current_rules(
            simulation_time
        )

        # ----------------------------------------------------------
        # Otkazivanje svih sortie-ja koji nisu počeli pre IFR uslova
        # ----------------------------------------------------------
        if use_instrument:
            for sortie in planned_sorties:
                if not sortie.started and not sortie.cancelled:
                    sortie.cancelled = True
                    sortie.status = "CANCELLED_IFR"

            # Ako fizički vazduhoplov nije započeo nijedan sortie
            # i još je u statusu PLANNED, označavamo ga kao CANCELLED.
            for aircraft in fleet:
                if aircraft.status == "PLANNED":
                    aircraft.status = "CANCELLED"

        # ----------------------------------------------------------
        # Aktiviranje sortie-ja u planirano vreme
        # ----------------------------------------------------------
        if not use_instrument:
            for sortie in planned_sorties:
                if sortie.started or sortie.cancelled:
                    continue

                if sortie.takeoff_time_sec > simulation_time:
                    continue

                # Sortie истог физичког ваздухоплова морају се
                # активирати редом, без обзира на стохастички jitter.
                earlier_sortie_unresolved = any(
                    other.aircraft_type == sortie.aircraft_type
                    and other.aircraft_id == sortie.aircraft_id
                    and other.sortie_id < sortie.sortie_id
                    and not other.completed
                    and not other.cancelled
                    for other in planned_sorties
                )

                if earlier_sortie_unresolved:
                    continue
                aircraft_key = (
                    sortie.aircraft_type,
                    sortie.aircraft_id,
                )

                aircraft = aircraft_registry[aircraft_key]

                # Turnaround zavisi od pripreme za sortie koji tek treba
                # da poleti: puna priprema ako se dopunjava gorivo,
                # odnosno samo smena posade/međuletni pregled ako se
                # gorivo ne dopunjava.
                if (
                    aircraft.status == "LANDED"
                    and aircraft.terminal_time is not None
                ):
                    required_turnaround_sec = (
                        aircraft.full_turnaround_time_sec
                        if sortie.refuelled
                        else aircraft.crew_change_turnaround_time_sec
                    )
                    aircraft.next_available_takeoff_time_sec = (
                        float(aircraft.terminal_time)
                        + float(required_turnaround_sec)
                    )

                if (
                    simulation_time
                    < aircraft.next_available_takeoff_time_sec
                ):
                    continue

                if aircraft.status not in {
                    "PLANNED",
                    "LANDED",
                }:
                    continue

                aircraft.prepare_for_sortie(
                    sortie_id=sortie.sortie_id,
                    refuelled=sortie.refuelled,
                    takeoff_time_sec=float(simulation_time),
                    activity_type=sortie.activity_type,
                    activity_duration_sec=(
                        sortie.activity_duration_sec
                    ),
                    migration_time_sec=(
                        sortie.migration_time_sec
                    ),
                    sortie_return_time_sec=(
                        sortie.sortie_return_time_sec
                    ),
                )

                if aircraft.current_fuel <= 0.0:
                    raise RuntimeError(
                        f"Cannot start sortie with zero fuel: "
                        f"{aircraft.type} aircraft {aircraft.id}, "
                        f"sortie {sortie.sortie_id}, "
                        f"refuelled={sortie.refuelled}"
                    )

                aircraft.status = "MIGRATION"

                aircraft.migration_start_time = float(
                    simulation_time
                )

                aircraft.migration_end_time = (
                    float(simulation_time)
                    + float(aircraft.migration_time_sec)
                )

                sortie.started = True
                sortie.actual_takeoff_time_sec = float(simulation_time)
                sortie.status = "ACTIVE"

                log(
                    f"[{simulation_time / 60:.2f} min] "
                    f"TAKEOFF: aircraft {aircraft.id} "
                    f"({aircraft.type}), "
                    f"sortie {sortie.sortie_id}; "
                    f"nominal="
                    f"{sortie.nominal_takeoff_time_sec / 60:.2f}; "
                    f"desired="
                    f"{sortie.takeoff_time_sec / 60:.2f}; "
                    f"actual="
                    f"{simulation_time / 60:.2f}; "
                    f"fuel={aircraft.current_fuel:.1f} kg"
                )

        # Prioritet se ažurira pre obrade vazduhoplova.
        for aircraft in fleet:
            aircraft.priority = aircraft.calculate_priority()

        fleet.sort(
            key=lambda aircraft: aircraft.priority,
            reverse=True,
        )

        # Samo čelo IFR reda sme da pokuša dobijanje sledećeg
        # prilaza. Time niži prioritet ne može da pretekne viši samo
        # zato što u tom trenutku ima povoljnije razdvajanje.
        ifr_queue_leader = (
            _select_ifr_queue_leader(
                fleet=fleet,
                aerodrome=aerodrome,
                simulation_time=simulation_time,
            )
            if use_instrument
            else None
        )

        for aircraft in fleet:
            if aircraft.status in TERMINAL_STATUSES:
                continue

            if aircraft.status == "PLANNED":
                continue

            # Sprečava da vazduhoplov u istom diskretnom koraku
            # dobije prilaz pre tačnog event-time trenutka u kojem je
            # stigao do READY_FOR_APPROACH. PokuÅ¡aj sledi u narednom
            # koraku, najviše DT_SEC kasnije.
            became_ready_this_step = False

            # ------------------------------------------------------
            # Prelazak na IFR prekida VFR aktivnost
            # ------------------------------------------------------
            if use_instrument:
                if aircraft.status in VFR_ACTIVITY_STATUSES:
                    aircraft.status = "RETURN_TO_AERODROME"

                    aircraft.return_start_time = float(
                        simulation_time
                    )

                    aircraft.return_end_time = (
                        float(simulation_time)
                        + float(
                            aircraft.sortie_return_time_sec
                        )
                    )

                    log(
                        f"[{simulation_time / 60:.2f} min] "
                        f"IFR TRANSITION: aircraft "
                        f"{aircraft.id} ({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}; "
                        f"activity interrupted"
                    )

                elif aircraft.status == "MIGRATION":
                    # Ako se vreme pogorša tokom odlaska ka
                    # zoni rada, zadatak se prekida i vazduhoplov
                    # započinje povratak na aerodrom.
                    aircraft.status = "RETURN_TO_AERODROME"

                    aircraft.return_start_time = float(
                        simulation_time
                    )

                    aircraft.return_end_time = (
                        float(simulation_time)
                        + float(
                            aircraft.sortie_return_time_sec
                        )
                    )

                    log(
                        f"[{simulation_time / 60:.2f} min] "
                        f"IFR TRANSITION: aircraft "
                        f"{aircraft.id} ({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}; "
                        f"outbound migration interrupted"
                    )

            # Статус фазе у којој ће у овом кораку бити
            # обрачуната потрошња горива. Чувамо га јер статус
            # касније у истом кораку може бити промењен.
            fuel_consumption_status = aircraft.status

            # ------------------------------------------------------
            # Odlazak od aerodroma do zone aktivnosti
            # ------------------------------------------------------
            if aircraft.status == "MIGRATION":
                if aircraft.migration_end_time is None:
                    aircraft.migration_start_time = float(
                        simulation_time
                    )

                    aircraft.migration_end_time = (
                        float(simulation_time)
                        + float(
                            aircraft.migration_time_sec
                        )
                    )

                _consume_until_event(
                    aircraft=aircraft,
                    simulation_time=simulation_time,
                    event_time=aircraft.migration_end_time,
                    mode="MIGRATION",
                )

                if (
                    simulation_time + config.DT_SEC
                    >= aircraft.migration_end_time
                ):
                    aircraft.entered_vfr_activity = True
                    aircraft.status = aircraft.activity_type

                    aircraft.activity_start_time = float(
                        aircraft.migration_end_time
                    )

                    aircraft.activity_end_time = (
                        float(aircraft.activity_start_time)
                        + float(
                            aircraft.activity_duration_sec
                        )
                    )

                    log(
                        f"[{aircraft.activity_start_time / 60:.2f} min] "
                        f"ACTIVITY START: aircraft "
                        f"{aircraft.id} ({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}; "
                        f"activity={aircraft.status}"
                    )

            # ------------------------------------------------------
            # Povratak sa zadatka prema aerodromu
            # ------------------------------------------------------
            elif aircraft.status == "RETURN_TO_AERODROME":
                if aircraft.return_end_time is None:
                    aircraft.return_start_time = float(
                        simulation_time
                    )

                    aircraft.return_end_time = (
                        float(simulation_time)
                        + float(
                            aircraft.sortie_return_time_sec
                        )
                    )

                _consume_until_event(
                    aircraft=aircraft,
                    simulation_time=simulation_time,
                    event_time=aircraft.return_end_time,
                    mode="RETURN_TO_AERODROME",
                )

                if (
                    simulation_time + config.DT_SEC
                    >= aircraft.return_end_time
                ):
                    aircraft.entered_ready_for_approach = True
                    aircraft.status = "READY_FOR_APPROACH"
                    aircraft.ready_for_approach_time = float(
                        aircraft.return_end_time
                    )
                    became_ready_this_step = True

                    log(
                        f"[{aircraft.return_end_time / 60:.2f} min] "
                        f"READY FOR APPROACH: aircraft "
                        f"{aircraft.id} ({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}"
                    )

            # ------------------------------------------------------
            # Izvršavanje VFR aktivnosti
            # ------------------------------------------------------
            elif aircraft.status in VFR_ACTIVITY_STATUSES:
                if aircraft.activity_end_time is None:
                    aircraft.activity_end_time = (
                        float(aircraft.activity_start_time)
                        + float(
                            aircraft.activity_duration_sec
                        )
                    )

                _consume_until_event(
                    aircraft=aircraft,
                    simulation_time=simulation_time,
                    event_time=aircraft.activity_end_time,
                    mode=aircraft.status,
                )

                if (
                    simulation_time + config.DT_SEC
                    >= aircraft.activity_end_time
                ):

                    sortie_key = (
                        aircraft.type,
                        aircraft.id,
                        aircraft.sortie_id,
                    )

                    current_sortie = sortie_by_key.get(sortie_key)

                    if current_sortie is not None:
                        current_sortie.actual_activity_duration_sec = (
                            float(aircraft.activity_end_time)
                            - float(aircraft.activity_start_time)
                        )
                        
                    aircraft.status = "RETURN_TO_AERODROME"

                    aircraft.return_start_time = float(
                        aircraft.activity_end_time
                    )

                    aircraft.return_end_time = (
                        float(aircraft.activity_end_time)
                        + float(
                            aircraft.sortie_return_time_sec
                        )
                    )

                    sortie_key = (
                        aircraft.type,
                        aircraft.id,
                        aircraft.sortie_id,
                    )

                    current_sortie = sortie_by_key.get(sortie_key)

                    if current_sortie is not None:
                        current_sortie.actual_activity_duration_sec = (
                            float(aircraft.activity_end_time)
                            - float(aircraft.activity_start_time)
                        )


                    log(
                        f"[{aircraft.activity_end_time / 60:.2f} min] "
                        f"ACTIVITY END: aircraft "
                        f"{aircraft.id} ({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}; "
                        f"return to aerodrome started"
                    )

            # ------------------------------------------------------
            # Holding
            # ------------------------------------------------------
            elif aircraft.status == "HOLDING":
                _account_holding_until(
                    aircraft,
                    simulation_time,
                )

            # ------------------------------------------------------
            # Prilaz
            # ------------------------------------------------------
            elif aircraft.status == "APPROACH":
                remaining_approach_sec = max(
                    0.0,
                    float(aircraft.landing_time)
                    - float(simulation_time),
                )

                burn_seconds = min(
                    config.DT_SEC,
                    remaining_approach_sec,
                )

                aircraft.consume_fuel(
                    burn_seconds,
                    mode="APPROACH",
                )

            # ------------------------------------------------------
            # Povratak od MAPt-a do IAF-a posle go-around-a
            # ------------------------------------------------------
            elif aircraft.status == "GO_AROUND_TRANSITION":
                if aircraft.go_around_transition_end_time is None:
                    raise RuntimeError(
                        "GO_AROUND_TRANSITION without an end time: "
                        f"{aircraft.type} {aircraft.id}, "
                        f"sortie {aircraft.sortie_id}"
                    )

                _consume_until_event(
                    aircraft=aircraft,
                    simulation_time=simulation_time,
                    event_time=(
                        aircraft.go_around_transition_end_time
                    ),
                    mode="TRANSITION",
                )

                if (
                    simulation_time + config.DT_SEC
                    >= aircraft.go_around_transition_end_time
                ):
                    ready_time = float(
                        aircraft.go_around_transition_end_time
                    )
                    aircraft.entered_ready_for_approach = True
                    aircraft.status = "READY_FOR_APPROACH"
                    aircraft.ready_for_approach_time = ready_time
                    aircraft.go_around_transition_end_time = None
                    became_ready_this_step = True

                    log(
                        f"[{ready_time / 60:.2f} min] "
                        f"READY AFTER GO-AROUND: aircraft "
                        f"{aircraft.id} ({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}; "
                        f"go-arounds={aircraft.go_around_count}; "
                        f"fuel={aircraft.current_fuel:.1f} kg"
                    )

            # ------------------------------------------------------
            # Nestanak goriva
            # ------------------------------------------------------
            if aircraft.current_fuel <= 0:
                aircraft.crashed_from_status = (
                    fuel_consumption_status
                )

                _set_terminal_status(
                    aircraft,
                    "CRASHED",
                    simulation_time,
                )

                record_sortie_result(aircraft)

                log(
                    f"[{simulation_time / 60:.2f} min] "
                    f"CRASH: aircraft {aircraft.id} "
                    f"({aircraft.type}), "
                    f"sortie {aircraft.sortie_id}; "
                    f"from_status="
                    f"{aircraft.crashed_from_status}; "
                    f"go-arounds="
                    f"{aircraft.go_around_count}; "
                    f"fuel={aircraft.current_fuel:.1f} kg"
                )

                continue

            # ------------------------------------------------------
            # Zavrsetak prilaza i sletanje
            # ------------------------------------------------------
            if (
                aircraft.status == "APPROACH"
                and aircraft.landing_time is not None
                and (
                    simulation_time + config.DT_SEC
                    >= aircraft.landing_time
                )
            ):
                planned_landing_time = float(
                    aircraft.landing_time
                )

                # Odluka se donosi tek na kraju konkretnog pokuÅ¡aja
                # prilaza, neposredno pre planiranog dodira PSS.
                if (
                    use_instrument
                    and np.random.random()
                    < aircraft.go_around_probability
                ):
                    aircraft.go_around_count += 1

                    missed_approach_factor = float(
                        np.random.triangular(0.90, 1.10, 1.20)
                    )

                    realized_missed_approach_time_sec = (
                        float(aircraft.missed_approach_to_iaf_time_sec)
                        * missed_approach_factor
                    )

                    # zadrzavanje drugih vazduhoplova u holdingu dok 
                    # vauzduhoplov koji je produzio na go around ne dostigne svoj holding 
                    # po proceduri za MAPT (priblizno mu treba GO_AROUND_HOLDING_RELEASE_FRACTION)

                    holding_release_delay_sec = (
                        realized_missed_approach_time_sec
                        * float(config.GO_AROUND_HOLDING_RELEASE_FRACTION)
                    )

                    new_block_start = planned_landing_time
                    new_release_time = (
                        planned_landing_time
                        + holding_release_delay_sec
                    )

                    if (
                        aerodrome.go_around_holding_release_time_sec
                        <= new_block_start
                    ):
                        aerodrome.go_around_holding_block_start_sec = (
                            new_block_start
                        )
                    else:
                        aerodrome.go_around_holding_block_start_sec = min(
                            aerodrome.go_around_holding_block_start_sec,
                            new_block_start,
                        )

                    aerodrome.go_around_holding_release_time_sec = max(
                        aerodrome.go_around_holding_release_time_sec,
                        new_release_time,
                    )

                    # Vazduhoplov napušta prilaz i prelazi u MAPt–IAF tranziciju.
                    aircraft.status = "GO_AROUND_TRANSITION"

                    aircraft.go_around_transition_end_time = (
                        planned_landing_time
                        + realized_missed_approach_time_sec
                    )

                    aircraft.approach_start = None
                    aircraft.landing_time = None

                    # Ponovljeni prilaz dobija novu stohasticku realizaciju.
                    aircraft.realized_approach_duration_sec = None
                    aircraft.realized_approach_is_instrument = None
                    log(
                        f"[{planned_landing_time / 60:.2f} min] "
                        f"GO-AROUND: aircraft {aircraft.id} "
                        f"({aircraft.type}), "
                        f"sortie {aircraft.sortie_id}; "
                        f"return to IAF at "
                        f"{aircraft.go_around_transition_end_time / 60:.2f} "
                        f"min; count={aircraft.go_around_count}; "
                        f"MAPt-IAF duration="
                        f"{realized_missed_approach_time_sec / 60:.2f} min; "
                        f"fuel={aircraft.current_fuel:.1f} kg; "
                        f"holding arrivals released after: "
                        f"{new_release_time / 60:.2f} min;"
                    )

                    continue

                aircraft.status = "LANDED"

                aircraft.terminal_time = float(
                    planned_landing_time
                )

                aircraft.next_available_takeoff_time_sec = (
                    float(aircraft.terminal_time)
                )

                aircraft.fuel_at_landing = float(
                    aircraft.current_fuel
                )

                aircraft.fuel_priority_at_landing = (
                    aircraft.fuel_status
                    in {
                        "LOW_FUEL",
                        "EMERGENCY",
                    }
                )

                record_sortie_result(aircraft)

                aerodrome.landed_aircraft.append(
                    (
                        aircraft.type,
                        aircraft.id,
                        aircraft.sortie_id,
                    )
                )

                aerodrome.waiting_times.append({
                    "aircraft_id": aircraft.id,
                    "sortie_id": aircraft.sortie_id,
                    "type": aircraft.type,
                    "wait_time": aircraft.holding_time_sec,

                    # Naziv kljuÄa je zadrÅ¾an zbog kompatibilnosti
                    # sa postojeÄ‡im analizama.
                    "arrival_time": aircraft.takeoff_time,

                    "remaining_fuel": aircraft.fuel_at_landing,
                    "fuel_margin_kg": (
                        aircraft.fuel_at_landing
                        - aircraft.type_specific_fuel_reserve
                    ),
                    "priority": aircraft.priority,
                    "fuel_priority_landing": (
                        aircraft.fuel_priority_at_landing
                    ),
                })

                log(
                    f"[{aircraft.landing_time / 60:.2f} min] "
                    f"LANDED: aircraft {aircraft.id} "
                    f"({aircraft.type}), "
                    f"sortie {aircraft.sortie_id}; "
                    f"fuel={aircraft.current_fuel:.1f} kg"
                )

                continue

            # ------------------------------------------------------
            # U IFR uslovima trenutno ne postoji raspoloživa PSS
            # za konkretan vazduhoplov koji nema RNP ability.
            # ------------------------------------------------------
            if (
                use_instrument
                and aircraft.status
                in {
                    "READY_FOR_APPROACH",
                    "HOLDING",
                }
                and _select_landing_runway(
                    aerodrome=aerodrome,
                    aircraft=aircraft,
                    use_instrument=True,
                    simulation_time=simulation_time,
                )
                is None
            ):
                if (
                    aircraft.status == "READY_FOR_APPROACH"
                    and not became_ready_this_step
                ):
                    if aircraft.fuel_status == "EMERGENCY":
                        _divert_aircraft(
                            aircraft=aircraft,
                            simulation_time=simulation_time,
                            reason=(
                                "no available IFR runway "
                                "for this aircraft"
                            ),
                            log=log,
                            record_sortie_result=(
                                record_sortie_result
                            ),
                        )
                    else:
                        _enter_holding(
                            aircraft,
                            simulation_time,
                        )

                elif (
                    aircraft.status == "HOLDING"
                    and aircraft.fuel_status == "EMERGENCY"
                ):
                    _divert_aircraft(
                        aircraft=aircraft,
                        simulation_time=simulation_time,
                        reason=(
                            "no available IFR runway "
                            "for this aircraft"
                        ),
                        log=log,
                        record_sortie_result=(
                            record_sortie_result
                        ),
                    )

                continue
            # ------------------------------------------------------
            # Vazduhoplov je stigao do tačke početka prilaza
            # ------------------------------------------------------
            if (
                aircraft.status == "READY_FOR_APPROACH"
                and not became_ready_this_step
                and (
                    not use_instrument
                    or aircraft is ifr_queue_leader
                )
            ):
                cleared = _try_clear_for_approach(
                    aerodrome=aerodrome,
                    aircraft=aircraft,
                    use_instrument=use_instrument,
                    separation_minima=separation_minima,
                    simulation_time=simulation_time,
                    from_holding=False,
                    log=log,
                    record_sortie_result=record_sortie_result,
                )

                if (
                    use_instrument
                    and not cleared
                    and aircraft.status
                    == "READY_FOR_APPROACH"
                ):
                    if aircraft.fuel_status == "EMERGENCY":
                        _divert_aircraft(
                            aircraft=aircraft,
                            simulation_time=simulation_time,
                            reason=(
                                "emergency endurance and "
                                "approach not immediately available"
                            ),
                            log=log,
                            record_sortie_result=record_sortie_result,
                        )
                    else:
                        _enter_holding(
                            aircraft,
                            simulation_time,
                        )

            # ------------------------------------------------------
            # Ponovni pokušaj dobijanja IFR prilaza iz holdinga
            # ------------------------------------------------------
            elif (
                aircraft.status == "HOLDING"
                and aircraft.holding_start is not None
                and simulation_time >= aircraft.holding_start
                and aircraft is ifr_queue_leader
            ):
                cleared = _try_clear_for_approach(
                    aerodrome=aerodrome,
                    aircraft=aircraft,
                    use_instrument=True,
                    separation_minima=separation_minima,
                    simulation_time=simulation_time,
                    from_holding=True,
                    log=log,
                    record_sortie_result=record_sortie_result,
                )

                if (
                    not cleared
                    and aircraft.status == "HOLDING"
                    and aircraft.fuel_status == "EMERGENCY"
                ):
                    _divert_aircraft(
                        aircraft=aircraft,
                        simulation_time=simulation_time,
                        reason=(
                            "emergency endurance and "
                            "approach unavailable from holding"
                        ),
                        log=log,
                        record_sortie_result=record_sortie_result,
                    )

        simulation_time += config.DT_SEC

    aerodrome.current_time = simulation_time

    return aerodrome, fleet, sortie_results, planned_sorties


def resolve_weather_minima(scenarios: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    vfr_scenario = next(
        (
            sc for sc in scenarios["scenarios"]
            if sc.get("parameters", {}).get("weather_conditions") == "VFR"
        ),
        None,
    )
    ifr_scenario = next(
        (
            sc for sc in scenarios["scenarios"]
            if sc.get("parameters", {}).get("weather_conditions") == "IFR"
        ),
        None,
    )
    if not vfr_scenario or not ifr_scenario:
        raise ValueError("Simulation scenarios must contain one VFR and one IFR scenario.")
    return vfr_scenario["separation_minima"], ifr_scenario["separation_minima"]


def build_transition_scenario(base_scenario: dict[str, Any], transition_min: int) -> dict[str, Any]:

    scenario = copy.deepcopy(base_scenario)
    scenario["id"] = f"TRANSITION_{transition_min:02d}MIN"
    scenario["name"] = f"VFR to IFR transition after {transition_min} min"
    scenario.setdefault("parameters", {})["weather_conditions"] = "VFR"
    scenario["parameters"]["weather_transition"] = {"at_min": transition_min, "to": "IFR"}
    return scenario