from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
from . import config

@dataclass
class PlannedSortie:
    """Jedan planirani let iz common_fpl.json."""

    aircraft_type: str
    aircraft_id: int
    sortie_id: int

    refuelled: bool

    # Nominalna vremena iz common_fpl.json.
    nominal_takeoff_time_sec: float
    nominal_activity_duration_sec: float
    nominal_migration_time_sec: float
    nominal_sortie_return_time_sec: float

    # Stohastički realizovana vremena za konkretnu replikaciju.
    takeoff_time_sec: float
    activity_duration_sec: float
    activity_type: str
    migration_time_sec: float
    sortie_return_time_sec: float

    status: str = "PLANNED"

    # Stvarno vreme polaska nakon primene turnaround ograničenja.
    actual_takeoff_time_sec: float | None = None

    # Stvarno ostvarena trajanja. Mogu biti kraÄ‡a ako IFR prekine fazu.
    actual_activity_duration_sec: float | None = None
    actual_migration_time_sec: float | None = None
    actual_return_time_sec: float | None = None

    started: bool = False
    completed: bool = False
    cancelled: bool = False

@dataclass
class SortieResult:
    aircraft_type: str
    aircraft_id: int
    sortie_id: int

    final_status: str

    takeoff_time_sec: float
    terminal_time_sec: float | None

    initial_fuel_kg: float
    final_fuel_kg: float
    type_specific_reserve_kg: float
    normal_fuel_load_kg: float
    fuel_consumption_holding_kg_min: float

    holding_time_sec: float
    holding_fuel_consumed_kg: float

    entered_holding: bool
    entered_approach: bool
    entered_vfr_activity: bool
    entered_ready_for_approach: bool
    
    was_low_fuel: bool
    was_emergency_endurance: bool
    was_below_reserve: bool

    fuel_priority_at_landing: bool
    go_around_count: int
    crashed_from_status: str | None

@dataclass(frozen=True)
class ApproachSequenceRecord:
    aircraft_type: str
    aircraft_id: int
    sortie_id: int | None

    wake_category: str
    approach_speed_kmh: float

    approach_start_time: float
    landing_time: float
    runway_occupancy_time_sec: float

class Aircraft:
    """Klasa koja predstavlja jedan vazduhoplov."""

    def __init__(self, ac_id, ac_type, performance_data):
        self.id = ac_id
        self.type = ac_type
        self.wake = performance_data["wake_category"]

        # Osnovne performance karakteristike
        self.aircraft_category = performance_data["aircraft_category"]
        self.speed_clss = performance_data["speed_class"]
        self.approach_speed = performance_data["approach_speed_kmh"]

        # Sposobnost korišćenja RNP prilaza za PSS 12R.
        # Ako polje nije navedeno u JSON-u, podrazumeva se False.
        self.rnp_approach_ability = bool(
            performance_data.get(
                "RNP_approach_ability",
                False,
            )
        )
        self.instrument_time = performance_data["instrument_approach_time_min"] * 60
        self.visual_time = performance_data["visual_approach_time_min"] * 60
        self.rot = performance_data["rot_seconds"]

        # Standardni turnaround sa doÐ¿unÑ˜avanjem goriva
        self.full_turnaround_time_sec = float(performance_data.get("turnaround_time_min", 30)) * 60.0

        # Vreme zamene posade / meÄ‘uletnog pregleda (ako postoji u bazi, u suprotnom podrazumevano 10 minuta)
        self.crew_change_turnaround_time_sec = float(
            performance_data.get("crew_change_turnaround_time_min", performance_data.get("turnaround_time_min", 10))
        ) * 60.0

        # Podrazumevano trenutno vreme pripreme
        self.turnaround_time_sec = self.full_turnaround_time_sec

        # Najraniji trenutak u kojem fizički vazduhoplov
        # može započeti sledeći sortie.
        self.next_available_takeoff_time_sec = 0.0
        self.landing_distance_required = performance_data.get("landing_distance_required_m", 1000)

        # Gorivo
        self.max_fuel_capacity = performance_data["max_fuel_capacity_kg"]
        self.normal_fuel_load = performance_data["normal_fuel_load_kg"]
        self.type_specific_fuel_reserve = performance_data["type_specific_reserve_kg"]

        # Potrošnja goriva po fazama leta (kg/min)
        self.fuel_consumption_approach = float(
            performance_data.get("fuel_consumption_approach_kg_min")
        )

        self.fuel_consumption_cruise = float(
            performance_data.get("fuel_consumption_cruise_kg_min")
        )

        self.fuel_consumption_aerial = float(
            performance_data.get("fuel_consumption_aerial_kg_min")
        )

        self.fuel_consumption_transition = float(
            performance_data.get("fuel_consumption_transition_kg_min")
        )

        self.fuel_consumption_holding = float(
            performance_data.get("fuel_consumption_holding_kg_min")
        )

        self.fuel_consumption_circuit = float(
            performance_data.get("fuel_consumption_transition_kg_min")
        )

        # Neuspeli prilaz / go-around.
        self.go_around_probability = float(
            performance_data.get("go_around_probability", 0.0)
        )
        if not 0.0 <= self.go_around_probability <= 1.0:
            raise ValueError(
                f"go_around_probability for {self.type} must be "
                "between 0 and 1"
            )

        self.missed_approach_to_iaf_time_sec = (
            float(
                performance_data.get(
                    "missed_approach_to_iaf_time_min",
                    0.0,
                )
            )
            * 60.0
        )
        if self.missed_approach_to_iaf_time_sec < 0.0:
            raise ValueError(
                f"missed_approach_to_iaf_time_min for {self.type} "
                "cannot be negative"
            )

        # Dinamički parametri
        # povezan sa planom leta
        # definisanim kroz common_fpl.json
        self.sortie_id = None
        self.takeoff_time = 0.0
        self.status = "PLANNED"
        self.fuel_status = "NORMAL"

        self.refuelled = False
        self.migration_time_sec = 0.0
        self.migration_start_time = None
        self.migration_end_time = None

        # VFR aktivnost pre prelaska na IFR.
        self.activity_type = None
        self.activity_duration_sec = 0.0
        self.activity_start_time = None
        self.activity_end_time = None

        self.sortie_return_time_sec = 0.0
        self.return_start_time = None
        self.return_end_time = None

        #Školski krug (aerodrome circuit)
        self.touch_and_go_count = 0
        self.last_touch_and_go_time = None

        self.activity_fuel_consumed = 0.0
        self.transition_fuel_consumed = 0.0
        # Event flags koje koristi analysis.py.
        self.entered_vfr_activity = False
        self.entered_ready_for_approach = False
        self.entered_holding = False
        self.entered_approach = False
        self.diverted_from_status = None
        self.crashed_from_status = None


        # Početno gorivo pri ulasku u simulaciju:
        # Biće određeno prilikom aktiviranja konkretnog sortie-ja,
        # na osnovu polja refuelled iz common_fpl.json.
        self.current_fuel = 0.0
        self.sortie_initial_fuel_kg = 0.0
        self.was_below_reserve = False

        # Početno stanje goriva određujemo prema stvarnoj količini goriva.
        if self.current_fuel <= self.type_specific_fuel_reserve:
            self.fuel_status = "EMERGENCY"
        elif self.current_fuel <= self.normal_fuel_load * 0.25:
            self.fuel_status = "LOW_FUEL"

        # Polja potrebna za operativnu logiku i eksperimentalne metrike
        self.assigned_runway = None
        self.assigned_star = None
        self.waiting_start = None
        self.ready_for_approach_time = None
        self.approach_start = None
        self.landing_time = None

        # Jednom realizovano stohasticko trajanje konkretnog
        # pokusaja prilaza.
        self.realized_approach_duration_sec = None
        self.realized_approach_is_instrument = None

        self.go_around_count = 0
        self.go_around_transition_end_time = None

        self.fuel_at_landing = None
        self.holding_start = None
        self.holding_pattern = None
        self.holding_fuel_consumed = 0.0
        self.holding_time_sec = 0.0
        self.holding_end_time = None
        self.holding_last_update_time = None
        self.terminal_time = None

        # Odvojeni istorijski indikatori stanja goriva.
        self.was_low_fuel = False
        self.was_emergency_endurance = False
        self.was_below_reserve = self.current_fuel <= self.type_specific_fuel_reserve
        # Zadržano radi kompatibilnosti sa starijim kodom; sada označava
        # da je preostala izdržljivost pala ispod emergency praga od 15 min.
        self.was_fuel_critical = False
        self.fuel_priority_at_landing = False
        self.priority = self.calculate_priority()

        # Za 3D (nije obavezno u engine-u, trenutno se ne koristi)
        self.trajectory_points = []
        self.current_position = None
        self.current_altitude = 0

    def prepare_for_sortie(
        self,
        sortie_id: int,
        refuelled: bool,
        takeoff_time_sec: float,
        activity_type: str,
        activity_duration_sec: float,
        migration_time_sec: float,
        sortie_return_time_sec: float
    ):
        """Priprema vazduhoplova za konkretan planirani let."""

        self.sortie_id = sortie_id
        self.refuelled = refuelled

        # Povezivanje refuelled za trenutni sortie sa turnaround vremenom:
        if self.refuelled:
            self.turnaround_time_sec = self.full_turnaround_time_sec
        else:
            self.turnaround_time_sec = self.crew_change_turnaround_time_sec
        
        self.takeoff_time = float(takeoff_time_sec)

        self.activity_type = activity_type
        self.activity_duration_sec = float(activity_duration_sec)
        self.migration_time_sec = float(migration_time_sec)
        self.sortie_return_time_sec = float(sortie_return_time_sec)
        self.status = "PLANNED"

        # Reset podataka koji pripadaju prethodnom sortie-ju
        self.assigned_runway = None
        self.assigned_star = None

        self.waiting_start = None
        self.ready_for_approach_time = None
        self.approach_start = None
        self.landing_time = None

        # Novi sortie mora dobiti novo realizovano trajanje prilaza.
        self.realized_approach_duration_sec = None
        self.realized_approach_is_instrument = None

        self.go_around_count = 0
        self.go_around_transition_end_time = None
        self.fuel_at_landing = None

        self.holding_start = None
        self.holding_pattern = None
        self.holding_fuel_consumed = 0.0
        self.holding_time_sec = 0.0
        self.holding_end_time = None
        self.holding_last_update_time = None

        self.return_start_time = None
        self.return_end_time = None

        self.terminal_time = None

        self.activity_fuel_consumed = 0.0
        self.transition_fuel_consumed = 0.0

        self.entered_vfr_activity = False
        self.entered_ready_for_approach = False
        self.entered_holding = False
        self.entered_approach = False

        self.diverted_from_status = None
        self.crashed_from_status = None

        self.was_low_fuel = False
        self.was_emergency_endurance = False
        self.was_below_reserve = False
        self.was_fuel_critical = False
        self.fuel_priority_at_landing = False
        if self.refuelled:
            fuel_variation = np.random.uniform(0.97, 1.00)

            self.current_fuel = min(
                float(self.normal_fuel_load) * fuel_variation,
                float(self.max_fuel_capacity),
            )
        else:
            self.current_fuel = min(
                float(self.current_fuel),
                float(self.max_fuel_capacity),
            )

        self.sortie_initial_fuel_kg = float(self.current_fuel)

        self.update_fuel_status()

    def calculate_priority(self):
        priority_score = 10
        if self.fuel_status == "EMERGENCY":
            priority_score += 30
        elif self.fuel_status == "LOW_FUEL":
            priority_score += 20

        if self.aircraft_category == "jet_airplane":
            priority_score += 10
        elif self.aircraft_category == "transport_airplane":
            priority_score += 6
        elif self.aircraft_category == "piston_airplane":
            priority_score += 5
        elif self.aircraft_category == "transport_helicopter":
            priority_score += 3

        return priority_score

    def update_fuel_status(self):

        if self.current_fuel <= self.type_specific_fuel_reserve:
            self.was_below_reserve = True

        minutes_to_empty = (
            self.current_fuel / self.fuel_consumption_holding
        )

        if minutes_to_empty < config.EMERGENCY_ENDURANCE_MIN:
            self.fuel_status = "EMERGENCY"
            self.was_emergency_endurance = True
            self.was_fuel_critical = True
            self.was_low_fuel = True
        elif minutes_to_empty < config.LOW_FUEL_ENDURANCE_MIN:
            self.fuel_status = "LOW_FUEL"
            self.was_low_fuel = True
        else:
            self.fuel_status = "NORMAL"

        self.priority = self.calculate_priority()
        return self.fuel_status

    def consume_fuel(self, seconds, mode="CRUISE"):
        """Troši gorivo prema konkretnoj fazi leta."""

        if mode == "HOLDING":
            rate_kg_min = self.fuel_consumption_holding

        elif mode == "APPROACH":
            rate_kg_min = self.fuel_consumption_approach

        elif mode == "AERIAL_WORK":
            rate_kg_min = self.fuel_consumption_aerial

        elif mode == "AERODROME_CIRCUIT":
            rate_kg_min = self.fuel_consumption_transition

        elif mode in {
            "MIGRATION",
            "RETURN_TO_AERODROME",
            "TRANSITION",
        }:
            rate_kg_min = self.fuel_consumption_transition

        else:
            # EN_ROUTE i podrazumevani CRUISE režim
            rate_kg_min = self.fuel_consumption_cruise

        rate_kg_sec = rate_kg_min / 60.0

        requested_amount = max(
            0.0,
            rate_kg_sec * float(seconds),
        )

        amount = min(
            float(self.current_fuel),
            requested_amount,
        )

        self.current_fuel -= amount

        if mode == "HOLDING":
            self.holding_fuel_consumed += amount

        elif mode in {
            "AERIAL_WORK",
            "EN_ROUTE",
            "AERODROME_CIRCUIT",
        }:
            self.activity_fuel_consumed += amount

        elif mode in {
            "MIGRATION",
            "RETURN_TO_AERODROME",
            "TRANSITION",
        }:
            self.transition_fuel_consumed += amount

        self.update_fuel_status()

        return amount

    def can_land_on_runway(
        self,
        runway_data,
        weather="DRY",
        landing_end="12L",
    ):
        threshold_to_use = None

        for threshold in runway_data["thresholds"]:
            if threshold["end"] == landing_end:
                threshold_to_use = threshold
                break

        if not threshold_to_use:
            return True, 0

        runway_length = runway_data["dimensions_m"]["length"]
        available_lda = runway_length - threshold_to_use.get("displacement_m", 0)
        required_distance = self.landing_distance_required
        if weather in ["WET", "RAIN", "SNOW"]:
            required_distance *= 1.3
        elif weather == "ICE":
            required_distance *= 1.5

        if required_distance <= available_lda:
            return True, available_lda - required_distance
        return False, required_distance - available_lda

    def get_remaining_flight_time(self, mode="HOLDING"):
        if mode == "APPROACH":
            rate = self.fuel_consumption_approach
        elif mode == "CRUISE":
            rate = self.fuel_consumption_cruise
        else:
            rate = self.fuel_consumption_holding
        return 0 if rate <= 0 else self.current_fuel / rate

    def __str__(self):
        fuel_percent = (self.current_fuel / self.normal_fuel_load) * 100
        return (
            f"Aircraft {self.id} ({self.type}) | Fuel: {self.current_fuel:.0f}kg "
            f"({fuel_percent:.0f}%) | Status: {self.fuel_status} | Priority: {self.priority}"
        )


class Aerodrome:
    """Klasa koja predstavlja jedan aerodrom i njegove resurse."""

    def __init__(self, layout_data, star_data, approach_rules):
        airport_obj = layout_data.get("airport") or {}
        self.name = (
            layout_data.get("name")
            or airport_obj.get("name")
            or airport_obj.get("icao")
            or "UNKNOWN"
        )
        
        self.runways = self._init_runways(layout_data)
        self.star_routes = star_data["procedures"]
        self.holding_patterns = star_data["holding_patterns"]
        self.current_time = 0

        # Vremenski interval privremenog zatvaranja PSS 12L/30R.
        # Ako su vrednosti None, zatvaranje nije aktivirano.
        self.runway_12l_closure_start_sec = None
        self.runway_12l_closure_end_sec = None

        # Privremena zabrana izlaska novog vazduhoplova iz holdinga
        # nakon go-around događaja.
        self.go_around_holding_block_start_sec = 0.0
        self.go_around_holding_release_time_sec = 0.0

        self.common_path_distance_nm = float(
            approach_rules["common_path_distance_nm"]
        )

        self.basic_separation_distance_nm = float(
            approach_rules["basic_separation_distance_nm"]
        )

        self.runway_buffer_sec = float(
            approach_rules.get("runway_buffer_sec", 0.0)
        )

        self.harris_delivery_error_std_sec = float(
            approach_rules.get(
                "harris_delivery_error_std_sec",
                20.0,
            )
        )

        self.harris_violation_probability = float(
            approach_rules.get(
                "harris_violation_probability",
                0.05,
            )
        )

        if self.harris_delivery_error_std_sec < 0.0:
            raise ValueError(
                "harris_delivery_error_std_sec cannot be negative"
            )

        if not 0.0 < self.harris_violation_probability < 0.5:
            raise ValueError(
                "harris_violation_probability must be "
                "greater than 0 and less than 0.5"
            )

        self.harris_normal_quantile = (
            NormalDist().inv_cdf(
                1.0 - self.harris_violation_probability
            )
        )

        self.wake_separation_time_sec = (
            approach_rules["wake_separation_time_sec"]
        )

        self.wake_separation_distance_nm = (
            approach_rules["wake_separation_distance_nm"]
        )

        self.validation_points = (
            approach_rules.get(
                "validation_points_distance_to_threshold_nm",
                {},
            )
        )

        self.last_approach: ApproachSequenceRecord | None = None
        self.last_sequence_constraints: dict[str, float] = {}

        # Svi vazduhoplovi koriste isti IFR prilaz za PSS 12L.

        self.landed_aircraft = []
        self.waiting_times = []

    def _init_runways(self, layout):
        if not isinstance(layout, dict):
            raise TypeError(f"layout_data must be dict, got: {type(layout)}")
        if "runways" not in layout:
            raise KeyError("'runways' not found in layout_data")

        runways = {}
        for rwy in layout["runways"]:
            ident = rwy["identifier"]
            runways[ident] = {
                "busy_until": 0,
                "last_wake": None,
                "length_m": rwy["dimensions_m"]["length"],
                "dimensions_m": rwy["dimensions_m"],
                "thresholds": rwy["thresholds"],
                "active": bool(rwy.get("active", True)),
            }
        return runways

    def configure_runway_12l_closure(
        self,
        ifr_start_time_sec: float | None,
    ) -> None:
        """
        Određuje početak i završetak privremenog zatvaranja
        PSS 12L/30R u odnosu na trenutak pojave IFR uslova.
        """

        # Svaka replikacija počinje bez aktivnog intervala zatvaranja.
        self.runway_12l_closure_start_sec = None
        self.runway_12l_closure_end_sec = None

        if not config.ENABLE_RUNWAY_12L_CLOSURE:
            return

        # Zatvaranje vezujemo isključivo za pojavu IFR uslova.
        if ifr_start_time_sec is None:
            return

        closure_delay_sec = float(
            config.RUNWAY_12L_CLOSURE_DELAY_SEC
        )
        closure_duration_sec = float(
            config.RUNWAY_12L_CLOSURE_DURATION_SEC
        )

        if closure_delay_sec < 0.0:
            raise ValueError(
                "RUNWAY_12L_CLOSURE_DELAY_SEC cannot be negative."
            )

        if closure_duration_sec <= 0.0:
            raise ValueError(
                "RUNWAY_12L_CLOSURE_DURATION_SEC must be positive."
            )

        self.runway_12l_closure_start_sec = (
            float(ifr_start_time_sec)
            + closure_delay_sec
        )

        self.runway_12l_closure_end_sec = (
            self.runway_12l_closure_start_sec
            + closure_duration_sec
        )

    def is_runway_open(
        self,
        runway_id: str,
        at_time_sec: float,
    ) -> bool:
        """
        Vraća True ako je tražena PSS raspoloživa
        u prosleđenom trenutku.
        """

        runway_data = self.runways.get(runway_id)

        # Nepostojeća ili trajno neaktivna PSS nije raspoloživa.
        if runway_data is None:
            return False

        if not bool(runway_data.get("active", False)):
            return False

        # Privremeno zatvaranje odnosi se samo na 12L/30R.
        if runway_id != config.LANDING_RUNWAY_ID:
            return True

        closure_start = self.runway_12l_closure_start_sec
        closure_end = self.runway_12l_closure_end_sec

        if closure_start is None or closure_end is None:
            return True

        return not (
            closure_start
            <= float(at_time_sec)
            < closure_end
        )

    def assign_star_route(self, aircraft):
        """Assign one of the available arrival routes for runway 12L/12R."""
        available = self.star_routes[
            "rw_12L_12R"
        ]["arrival_routes"]

        return str(
            np.random.choice(available)["identifier"]
        )

    @staticmethod
    def _matrix_value(
        matrix: dict,
        leader_category: str,
        follower_category: str,
    ) -> float:
        category_aliases = {
            "J": "SUPER",
            "H": "HEAVY",
            "M": "MEDIUM",
            "L": "LIGHT",
        }

        leader_key = str(leader_category).upper()
        follower_key = str(follower_category).upper()

        leader_key = category_aliases.get(
            leader_key,
            leader_key,
        )

        follower_key = category_aliases.get(
            follower_key,
            follower_key,
        )

        leader_row = matrix.get(
            leader_key,
            {},
        )

        return float(
            leader_row.get(
                follower_key,
                0.0,
            )
        )

    @staticmethod
    def _blumstein_headway_sec(
        common_path_distance_nm: float,
        required_spacing_nm: float,
        leader_speed_kt: float,
        follower_speed_kt: float,
    ) -> float:
        if common_path_distance_nm <= 0:
            raise ValueError(
                "common_path_distance_nm must be positive"
            )

        if required_spacing_nm < 0:
            raise ValueError(
                "required_spacing_nm cannot be negative"
            )

        if required_spacing_nm > common_path_distance_nm:
            raise ValueError(
                "Required spacing cannot exceed "
                "the common path distance"
            )

        if leader_speed_kt <= 0 or follower_speed_kt <= 0:
            raise ValueError(
                "Approach speeds must be positive"
            )

        # sledeći/prateći vazduhoplov je sporiji od vodećeg
        # dodeljeno razdvajanje se neće smanjivati u toku prilaza na sletanje
        if follower_speed_kt <= leader_speed_kt:
            return (
                3600.0
                * required_spacing_nm
                / leader_speed_kt
            )

        # sledeći vazduhoplov je brži i sustiže onog ispred sebe.
        return max(
            0.0,
            3600.0
            * (
                common_path_distance_nm / leader_speed_kt
                - (
                    common_path_distance_nm
                    - required_spacing_nm
                )
                / follower_speed_kt
            ),
        )

    @staticmethod
    def _harris_buffer_sec(
        required_spacing_nm: float,
        leader_speed_kt: float,
        follower_speed_kt: float,
        delivery_error_std_sec: float,
        normal_quantile: float,
    ) -> float:
        if required_spacing_nm < 0.0:
            raise ValueError(
                "required_spacing_nm cannot be negative"
            )

        if leader_speed_kt <= 0.0 or follower_speed_kt <= 0.0:
            raise ValueError(
                "Approach speeds must be positive"
            )

        if delivery_error_std_sec < 0.0:
            raise ValueError(
                "delivery_error_std_sec cannot be negative"
            )

        full_buffer_sec = (
            delivery_error_std_sec
            * normal_quantile
        )

        # Vodeći je brži od pratioca:
        # razmak se prirodno povećava, pa se Harris-ov
        # puni bafer može delimično ili potpuno apsorbovati.
        if leader_speed_kt > follower_speed_kt:
            natural_spacing_gain_sec = (
                3600.0
                * required_spacing_nm
                * (
                    1.0 / follower_speed_kt
                    - 1.0 / leader_speed_kt
                )
            )

            return max(
                0.0,
                full_buffer_sec
                - natural_spacing_gain_sec,
            )

        # Pratilac je jednako brz ili brži:
        # razmak se smanjuje u prilazu.
        return full_buffer_sec

    def required_approach_start_time(
        self,
        aircraft,
        follower_approach_duration_sec: float,
    ) -> tuple[float, dict[str, float]]:
        leader = self.last_approach

        # Kada nema prethodnog vazduhoplova.
        if leader is None:
            constraints = {
                "blumstein_ready_time": 0.0,
                "harris_buffer_sec": 0.0,
                "harris_ready_time": 0.0,
                "harris_normal_quantile": (self.harris_normal_quantile),
                "wake_ready_time": 0.0,
                "runway_ready_time": 0.0,
                "required_start_time": 0.0,
                "required_spacing_nm": 0.0,
                "wake_spacing_nm": 0.0,
                "wake_spacing_sec": 0.0,
            }
            return 0.0, constraints

        leader_speed_kt = (
            float(leader.approach_speed_kmh) / 1.852
        )

        follower_speed_kt = (
            float(aircraft.approach_speed) / 1.852
        )

        wake_distance_nm = self._matrix_value(
            self.wake_separation_distance_nm,
            leader.wake_category,
            aircraft.wake,
        )

        required_spacing_nm = max(
            self.basic_separation_distance_nm,
            wake_distance_nm,
        )

        blumstein_headway_sec = (
            self._blumstein_headway_sec(
                common_path_distance_nm=(
                    self.common_path_distance_nm
                ),
                required_spacing_nm=required_spacing_nm,
                leader_speed_kt=leader_speed_kt,
                follower_speed_kt=follower_speed_kt,
            )
        )

        harris_buffer_sec = (
            self._harris_buffer_sec(
                required_spacing_nm=required_spacing_nm,
                leader_speed_kt=leader_speed_kt,
                follower_speed_kt=follower_speed_kt,
                delivery_error_std_sec=(
                    self.harris_delivery_error_std_sec
                ),
                normal_quantile=(
                    self.harris_normal_quantile
                ),
            )
        )

        blumstein_ready_time = (
            leader.approach_start_time
            + blumstein_headway_sec
        )

        harris_ready_time = (
            blumstein_ready_time
            + harris_buffer_sec
        )

        wake_spacing_sec = self._matrix_value(
            self.wake_separation_time_sec,
            leader.wake_category,
            aircraft.wake,
        )

        wake_ready_time = (
            leader.landing_time
            + wake_spacing_sec
            - float(follower_approach_duration_sec)
        )

        runway_ready_time = (
            leader.landing_time
            + leader.runway_occupancy_time_sec
            + self.runway_buffer_sec
            - float(follower_approach_duration_sec)
        )

        required_start_time = max(
            harris_ready_time,
            wake_ready_time,
            runway_ready_time,
            0.0,
        )

        constraints = {
            "blumstein_headway_sec": blumstein_headway_sec,
            "blumstein_ready_time": blumstein_ready_time,
            "harris_buffer_sec": harris_buffer_sec,
            "harris_ready_time": harris_ready_time,
            "harris_normal_quantile": (
                self.harris_normal_quantile
            ),
            "wake_ready_time": wake_ready_time,
            "runway_ready_time": runway_ready_time,
            "required_start_time": required_start_time,
            "required_spacing_nm": required_spacing_nm,
            "wake_spacing_nm": wake_distance_nm,
            "wake_spacing_sec": wake_spacing_sec,
        }

        return required_start_time, constraints

    def can_land(
        self,
        aircraft,
        runway_id: str,
        approach_start_time: float | None = None,
        approach_duration_sec: float = 0.0,
        use_instrument: bool = True,
    ):
        if runway_id not in self.runways:
            return False, float("inf")

        requested_start_time = (
            float(approach_start_time)
            if approach_start_time is not None
            else float(self.current_time)
        )

        if not use_instrument:
            return True, 0.0

        required_start_time, constraints = (
            self.required_approach_start_time(
                aircraft=aircraft,
                follower_approach_duration_sec=(
                    approach_duration_sec
                ),
            )
        )

        self.last_sequence_constraints = constraints

        if requested_start_time < required_start_time:
            waiting_time = (
                required_start_time
                - requested_start_time
            )
            return False, waiting_time

        return True, 0.0

    def register_approach(
        self,
        aircraft,
        approach_start_time: float,
        landing_time: float,
    ) -> None:
        self.last_approach = ApproachSequenceRecord(
            aircraft_type=str(aircraft.type),
            aircraft_id=int(aircraft.id),
            sortie_id=aircraft.sortie_id,
            wake_category=str(aircraft.wake),
            approach_speed_kmh=float(
                aircraft.approach_speed
            ),
            approach_start_time=float(
                approach_start_time
            ),
            landing_time=float(landing_time),
            runway_occupancy_time_sec=float(
                aircraft.rot
            ),
        )