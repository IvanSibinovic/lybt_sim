# src/lybt_sim/models.py
import numpy as np

class Aircraft:
    """Klasa koja predstavlja jedan vazduhoplov"""
    def __init__(self, ac_id, ac_type, performance_data):
        self.id = ac_id
        self.type = ac_type
        self.wake = performance_data['wake_category']

        # Osnovne performance karakteristike
        self.approach_speed = performance_data['approach_speed_kmh']
        self.instrument_time = performance_data['instrument_approach_time_min'] * 60
        self.visual_time = performance_data['visual_approach_time_min'] * 60
        self.rot = performance_data['rot_seconds']
        self.landing_distance_required = performance_data.get('landing_distance_required_m', 1000)

        # Gorivo
        self.max_fuel_capacity = performance_data['max_fuel_capacity_kg']
        self.normal_fuel_load = performance_data['normal_fuel_load_kg']
        self.minimum_fuel_emergency = performance_data['minimum_fuel_emergency_kg']

        # Potrošnja goriva (kg/min)
        self.fuel_consumption_approach = performance_data['fuel_consumption_approach_kg_min']
        self.fuel_consumption_cruise = performance_data.get(
            'fuel_consumption_cruise_kg_min',
            performance_data['fuel_consumption_approach_kg_min'] * 1.5
        )
        self.fuel_consumption_holding = performance_data.get(
            'fuel_consumption_holding_kg_min',
            performance_data['fuel_consumption_approach_kg_min'] * 0.8
        )

        # Dinamički parametri
        self.arrival_time = 0
        self.status = "EN ROUTE"
        self.fuel_status = "NORMAL"

        # Realniji start fuel (kao ranije)
        fuel_probability = np.random.random()
        if fuel_probability < 0.7:
            fuel_percentage = np.random.uniform(0.7, 1.0)
            self.current_fuel = self.normal_fuel_load * fuel_percentage
            self.fuel_status = "NORMAL"
        elif fuel_probability < 0.9:
            fuel_percentage = np.random.uniform(0.3, 0.7)
            self.current_fuel = self.normal_fuel_load * fuel_percentage
            self.fuel_status = "LOW_FUEL"
        else:
            fuel_percentage = np.random.uniform(0.1, 0.3)
            self.current_fuel = self.normal_fuel_load * fuel_percentage
            self.fuel_status = "EMERGENCY"

        self.current_fuel = min(self.current_fuel, self.max_fuel_capacity)

        # Dodatni parametri
        self.assigned_runway = None
        self.assigned_star = None
        self.waiting_start = None
        self.approach_start = None
        self.landing_time = None
        self.holding_start = None
        self.holding_pattern = None
        self.priority = self.calculate_priority()

        # Za 3D (nije obavezno u engine-u, ali ostavljamo)
        self.trajectory_points = []
        self.current_position = None
        self.current_altitude = 0

    def calculate_priority(self):
        priority_score = 10

        if self.fuel_status == "EMERGENCY":
            priority_score += 30
        elif self.fuel_status == "LOW_FUEL":
            priority_score += 15

        if "MiG" in self.type:
            priority_score += 10
        elif "CASA" in self.type or "An-26" in self.type:
            priority_score += 5

        if "H145" in self.type or "Mi-17" in self.type:
            priority_score += 3

        return priority_score

    def update_fuel_status(self):
        minutes_to_empty = self.current_fuel / self.fuel_consumption_holding
        if minutes_to_empty < 30:
            self.fuel_status = "EMERGENCY"
        elif minutes_to_empty < 45:
            self.fuel_status = "LOW_FUEL"
        else:
            self.fuel_status = "NORMAL"
        return self.fuel_status

    def consume_fuel(self, seconds, mode="CRUISE"):
        # Convert kg/min to kg/sec
        if mode == "HOLDING":
            rate = self.fuel_consumption_holding / 60
        elif mode == "APPROACH":
            rate = self.fuel_consumption_approach / 60
        else:
            rate = self.fuel_consumption_cruise / 60
            
        amount = rate * seconds
        self.current_fuel = max(0, self.current_fuel - amount)
        
        # Update status based on remaining percentage
        percent = (self.current_fuel / self.max_fuel_capacity) * 100
        if percent < 10:
            self.fuel_status = "EMERGENCY"
        elif percent < 20:
            self.fuel_status = "LOW_FUEL"
            
        return amount

    def can_land_on_runway(self, runway_data, weather="DRY"):
        threshold_to_use = None
        for threshold in runway_data['thresholds']:
            if '12R' in threshold['end'] and self.assigned_runway and '12R' in self.assigned_runway:
                threshold_to_use = threshold
                break
            elif '30L' in threshold['end'] and self.assigned_runway and '30L' in self.assigned_runway:
                threshold_to_use = threshold
                break

        if not threshold_to_use:
            return True, 0

        runway_length = runway_data['dimensions_m']['length']
        if threshold_to_use.get('displaced_threshold', False):
            displacement = threshold_to_use.get('displacement_m', 0)
            available_lda = runway_length - displacement
        else:
            available_lda = runway_length

        required_distance = self.landing_distance_required
        if weather in ["WET", "RAIN", "SNOW"]:
            required_distance *= 1.3
        elif weather == "ICE":
            required_distance *= 1.5

        if required_distance <= available_lda:
            return True, (available_lda - required_distance)
        return False, (required_distance - available_lda)

    def get_remaining_flight_time(self, mode="HOLDING"):
        if mode == "APPROACH":
            rate = self.fuel_consumption_approach
        elif mode == "CRUISE":
            rate = self.fuel_consumption_cruise
        else:
            rate = self.fuel_consumption_holding

        if rate <= 0:
            return 0
        return self.current_fuel / rate

    def __str__(self):
        fuel_percent = (self.current_fuel / self.normal_fuel_load) * 100
        return (f"Aircraft {self.id} ({self.type}) | "
                f"Fuel: {self.current_fuel:.0f}kg ({fuel_percent:.0f}%) | "
                f"Status: {self.fuel_status} | Priority: {self.priority}")

class Aerodrome:
    """Klasa koja predstavlja aerodrom sa svim resursima"""
    def __init__(self, layout_data, star_data):
        # layout može biti:
        # 1) {"name": "...", "runways": [...]}
        # 2) {"airport": {"name": "...", ...}, "runways": [...]}
        airport_obj = layout_data.get("airport") or {}
        self.name = layout_data.get("name") or airport_obj.get("name") or airport_obj.get("icao") or "UNKNOWN"

        self.runways = self._init_runways(layout_data)
        self.star_routes = star_data['procedures']
        self.holding_patterns = star_data['holding_patterns']
        self.current_time = 0

        self.landed_aircraft = []
        self.waiting_times = []
        self.fuel_used = []


    def _init_runways(self, layout):
        # layout može biti dict sa "runways", ali ako nije – pokaži šta je stiglo
        if not isinstance(layout, dict):
            raise TypeError(f"layout_data must be dict, got: {type(layout)}")

        if "runways" not in layout:
            # DEBUG: šta zapravo imamo?
            print("DEBUG layout keys:", list(layout.keys())[:30])
            raise KeyError("'runways' not found in layout_data")

        runways = {}
        for rwy in layout["runways"]:
            ident = rwy["identifier"]
            runways[ident] = {
                "busy_until": 0,
                "length_m": rwy["dimensions_m"]["length"],
                "dimensions_m": rwy["dimensions_m"],   # bitno za can_land_on_runway()
                "thresholds": rwy["thresholds"],
                "active": True
            }
        return runways

    def assign_star_route(self, aircraft, arrival_direction):
        if arrival_direction in ['NORTH', 'EAST']:
            available = self.star_routes['rw_12L_12R']['arrival_routes']
        else:
            available = self.star_routes['rw_30L_30R']['arrival_routes']

        star = np.random.choice(available)
        return star['identifier']

    def can_land(self, aircraft, runway_id):
        if runway_id not in self.runways:
            print(f"Upozorenje: Pista '{runway_id}' ne postoji. Dostupne: {list(self.runways.keys())}")
            return False, float('inf')

        runway = self.runways[runway_id]
        if self.current_time < runway['busy_until']:
            return False, runway['busy_until'] - self.current_time

        return True, 0
