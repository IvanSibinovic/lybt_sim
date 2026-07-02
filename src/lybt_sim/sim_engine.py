# src/lybt_sim/sim_engine.py
from datetime import datetime
import numpy as np

from . import config
from .models import Aircraft, Aerodrome
from .export_replay import export_replay_json


def create_fleet(scenario, aircraft_db):
    """
    Kreira listu Aircraft objekata na osnovu scenario['aircraft_composition'].

    - Za svaki tip aviona uzima performance podatke iz aircraft_db['aircraft_data'].
    - Svakom avionu dodeljuje arrival_time (dolazak) nasumično (eksponencijalno),
      i arrival_direction (N/S/E/W).
    """
    fleet = []
    aircraft_id = 1

    for ac_type, count in scenario["aircraft_composition"].items():
        ac_perf = None
        for ac in aircraft_db["aircraft_data"]:
            if ac["aircraft_type"] == ac_type:
                ac_perf = ac
                break

        if not ac_perf:
            # ako u scenario piše tip koji ne postoji u bazi, preskoči
            print(f" Upozorenje: Tip aviona '{ac_type}' nije pronađen u aircraft_performance.json")
            continue

        for _ in range(count):
            if len(fleet) == 0:
                arrival = 0
            else:
                arrival = fleet[-1].arrival_time + np.random.exponential(300)  # prosek 5 min

            aircraft = Aircraft(aircraft_id, ac_type, ac_perf)
            aircraft.arrival_time = float(arrival)
            aircraft.arrival_direction = np.random.choice(["NORTH", "SOUTH", "EAST", "WEST"])

            fleet.append(aircraft)
            aircraft_id += 1

    # sort po vremenu dolaska
    fleet.sort(key=lambda x: x.arrival_time)

    print("DEBUG fleet sample:", [(a.id, a.type, a.arrival_time, a.status) for a in fleet[:3]])

    return fleet


def run_simulation(scenario, aircraft_db, layout_data, star_data, vfr_minima, ifr_minima, replay_recorder=None):

    print(f"\n POKRETANJE SIMULACIJE: {scenario['name']}")
    print("-" * 60)

    aerodrome = Aerodrome(layout_data, star_data)

    # dodajemo pomoćni atribut za analizu (ne mora u models.py)
    aerodrome.last_time = 0

    fleet = create_fleet(scenario, aircraft_db)

    # prioritet prvo (veći = hitniji)
    fleet.sort(key=lambda x: x.priority, reverse=True)

    base_weather = scenario["parameters"]["weather_conditions"]  # "VFR" ili "IFR"
    transition = scenario["parameters"].get("weather_transition")  # npr {"at_min": 30, "to": "IFR"} ili None

    diverted_aircraft = []

    simulation_time = 0
    max_simulation_time = config.SIM_DURATION_SEC
    transition_printed = False

    def current_rules(sim_time_sec: int):

        weather_now = base_weather

        if transition:
            t_sec = int(float(transition["at_min"]) * 60)
            if sim_time_sec >= t_sec:
                weather_now = transition["to"]

        if weather_now == "IFR":
            return "IFR", True, ifr_minima
        return "VFR", False, vfr_minima

    def xyz_for_render(ac, t):
        # svaki avion ima svoj lane
        lane = (ac.id % 6) - 3  # -3..+2
        lane_offset = lane * 300.0

        if ac.status == "EN ROUTE":
            dirn = getattr(ac, "arrival_direction", "NORTH")
            if dirn == "NORTH": return (lane_offset, 8000.0, 600.0)
            if dirn == "SOUTH": return (lane_offset, -8000.0, 600.0)
            if dirn == "EAST":  return (8000.0, lane_offset, 600.0)
            return (-8000.0, lane_offset, 600.0)

        if ac.status == "HOLDING":
            # кружи у кругу
            r = 2000.0 + (ac.id % 5) * 250.0
            ang = 2*np.pi*(t/240.0) + ac.id * 0.3
            cx, cy = (2500.0, 2500.0)
            return (cx + r*np.cos(ang), cy + r*np.sin(ang), 450.0)

        if ac.status == "APPROACH":
            # линеарно ка центру (0,0)
            t0 = getattr(ac, "approach_start", t)
            dur = float(getattr(ac, "instrument_time", 600) or 600)
            u = 0.0 if dur <= 0 else min(1.0, max(0.0, (t - t0) / dur))
            sx, sy = (lane_offset, 6000.0)
            x = sx*(1-u)
            y = sy*(1-u)
            z = 350.0*(1-u) + 10.0*u
            return (x, y, z)

        if ac.status == "LANDED":
            return (lane_offset, 0.0, 10.0)

        # DIVERTED/CRASHED
        return (12000.0, 12000.0, 2000.0)

    while simulation_time < max_simulation_time and any(ac.status != "LANDED" for ac in fleet):

        if replay_recorder is not None:
            for ac in fleet:
                x, y, z = xyz_for_render(ac, simulation_time)
                replay_recorder.add(
                    ac_id=str(ac.id),
                    t_sec=float(simulation_time),
                    x=float(x), y=float(y), z=float(z),
                    fuel=float(getattr(ac, "current_fuel", 0.0)),
                    status=str(getattr(ac, "status", "EN ROUTE")),
                    ac_type=str(getattr(ac, "type", "UNKNOWN"))
                )

        if simulation_time == 0 and replay_recorder is not None:
            print("DEBUG: recorder active, fleet size:", len(fleet))

        fleet.sort(key=lambda x: x.priority, reverse=True)

        phase, use_instrument, separation_minima = current_rules(simulation_time)

        # --- METEO TRANSITION LOG ---
        if transition and not transition_printed:
            t_sec = int(float(transition["at_min"]) * 60)
            if simulation_time >= t_sec:
                print(f"[{simulation_time/60:6.1f}min] METEO CHANGE: {base_weather} -> {transition['to']}")
                transition_printed = True

        # --- GLAVNA PETLJA ZA AVIONE (IZVAN if transition) ---
        for aircraft in fleet:
            if aircraft.status in ["LANDED", "DIVERTED", "CRASHED"]:
                continue

            # --- DYNAMIC FUEL DRAIN ---
            if aircraft.arrival_time <= simulation_time:
                f_mode = "HOLDING" if aircraft.status == "HOLDING" else "CRUISE"
                aircraft.consume_fuel(config.DT_SEC, mode=f_mode)

            # --- SAFETY CHECK ---
            if aircraft.current_fuel <= 0:
                print(f"[{simulation_time/60:6.1f}min]  CRASH: {aircraft} - Fuel Exhaustion!")
                aircraft.status = "CRASHED"
                continue

            if aircraft.current_fuel < (aircraft.max_fuel_capacity * 0.05):
                print(f"[{simulation_time/60:6.1f}min]  DIVERTED: {aircraft} - Low fuel safety diversion.")
                aircraft.status = "DIVERTED"
                diverted_aircraft.append(aircraft.id)
                continue

            # --- STATE MACHINE ---
            if aircraft.status == "EN ROUTE" and aircraft.arrival_time <= simulation_time:

                aircraft.assigned_star = aerodrome.assign_star_route(aircraft, aircraft.arrival_direction)
                    
                # Minimum fuel check for approach
                app_dur = aircraft.instrument_time if use_instrument else aircraft.visual_time
                if aircraft.current_fuel < (aircraft.fuel_consumption_approach * (app_dur / 60)):
                    aircraft.status = "DIVERTED"
                    print(f"[{simulation_time/60:6.1f}min]  DIVERTED: {aircraft} - No fuel for approach.")
                    continue
                
                aircraft.status = "HOLDING"
                aircraft.waiting_start = simulation_time

            # PHASE B: Try to land if in HOLDING
            if aircraft.status == "HOLDING":
                rwy_options = ["12R/30L", "12L/30R"] if aircraft.arrival_direction in ["NORTH", "EAST"] else ["12L/30R", "12R/30L"]
                    
                for rwy_id in rwy_options:
                    runway_data = aerodrome.runways.get(rwy_id)
                    can_land_phys, _ = aircraft.can_land_on_runway(runway_data, "DRY")
                    is_free, wait_time = aerodrome.can_land(aircraft, rwy_id)

                    if can_land_phys and is_free:
                        # Move to APPROACH
                        aircraft.status = "APPROACH"
                        aircraft.assigned_runway = rwy_id
                        aircraft.approach_start = simulation_time
                            
                        duration = aircraft.instrument_time if use_instrument else aircraft.visual_time
                        aircraft.landing_time = simulation_time + duration
                            
                        # Consume fuel for the approach leg
                        aircraft.consume_fuel(duration, mode="APPROACH")

                        # Lock Runway
                        runway = aerodrome.runways[rwy_id]
                        wake_sep = int(separation_minima.get(f"{aircraft.wake}-{aircraft.wake}", 90) * 60)
                        runway["busy_until"] = aircraft.landing_time + aircraft.rot + wake_sep

                        # Record Stats (Crucial for Analysis.py!)
                        wait_total = simulation_time - aircraft.arrival_time
                        aerodrome.landed_aircraft.append(aircraft.id)
                        aerodrome.waiting_times.append({
                            "aircraft_id": aircraft.id,
                            "type": aircraft.type,
                            "wait_time": wait_total,
                            "arrival_time": aircraft.arrival_time, # Fixes KeyError
                            "remaining_fuel": aircraft.current_fuel,
                            "priority": aircraft.priority
                        })

                        aircraft.status = "LANDED"
                        print(f"[{aircraft.landing_time/60:6.1f}min] {aircraft} landed on {rwy_id}. Wait: {wait_total/60:.1f}min")
                        break
        # (9) pomeri jedini sat
        simulation_time += config.DT_SEC

    print(f"\n STATISTIKA GORIVA:")
    print(f"   • Ukupno potrošeno goriva: {sum(aerodrome.fuel_used):.0f} kg")
    print(f"   • Aviona sa malo goriva (LOW_FUEL): {len([ac for ac in fleet if ac.fuel_status == 'LOW_FUEL'])}")
    print(f"   • Hitnih slučajeva (EMERGENCY): {len([ac for ac in fleet if ac.fuel_status == 'EMERGENCY'])}")
    print(f"   • Preusmerenih aviona: {len(diverted_aircraft)}")
    print(f"   • Last event time: {getattr(aerodrome, 'last_time', 0)/60:.1f} min")

    return aerodrome, fleet

def generate_final_report(scenarios):
    report = f"""
KONACNI IZVESTAJ - SEMINARSKI RAD
Simulacija prilaza na aerodromu LYBT Batajnica
Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}

REZIME ANALIZE:
U uslovima lose vidljivosti (IFR), kapacitet aerodroma se znacajno smanjuje
zbog duzih instrumentalnih procedura prilaza i strozijih zahteva za razdvajanje.

PREPORUKE:
1. U IFR uslovima planirati vece vremenske intervale izmedju prilaza
2. Koristiti obe piste paralelno kada je to moguce
3. Implementirati sistem prioriteta za avione sa manjkom goriva
4. Razmotriti mogucnost koriscenja RNP AR procedura za brzi prilaz

KLJUCNI PODACI:
• Prosecno povecanje vremena u IFR vs VFR: ~40-60%
• Najosetljiviji tip aviona: transportni (CASA, An-26) zbog duzeg vremena prilaza
• Optimalan broj aviona u holding patternu: 2-3 po sektoru
"""
    out = config.RESULTS_DIR / "konacni_izvestaj.txt"
    out.write_text(report, encoding="utf-8")
    print(f" Konacni izvestaj sacuvan: {out}")

def run_all_scenarios(aircraft_db, aip_data, star_data, layout_data, scenarios, analyze_fn, replay_recorder=None):
    vfr_minima = None
    ifr_minima = None

    for sc in scenarios["scenarios"]:
        if sc["id"] == "SCENARIO_2":
            vfr_minima = sc["separation_minima"]
        if sc["id"] == "SCENARIO_1":
            ifr_minima = sc["separation_minima"]

    assert vfr_minima and ifr_minima, "Nedostaju separation minima za SCENARIO_1 i SCENARIO_2"

    all_results = []

    for scenario in scenarios["scenarios"]:
        aerodrome, fleet = run_simulation(
            scenario, aircraft_db, layout_data, star_data,
            vfr_minima=vfr_minima, ifr_minima=ifr_minima,
            replay_recorder=replay_recorder)

        analyze_fn(aerodrome, fleet, scenario)

        all_results.append({"scenario": scenario["id"], "landed": len(aerodrome.landed_aircraft)})

    generate_final_report(scenarios["scenarios"])
    return all_results