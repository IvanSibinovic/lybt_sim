# src/lybt_sim/trajectory.py
import math
import numpy as np

from . import config

def latlon_to_xy_m(lat, lon, ref_lat, ref_lon):
    R = 6371000.0
    dlat = math.radians(lat - ref_lat)
    dlon = math.radians(lon - ref_lon)
    x = R * dlon * math.cos(math.radians(ref_lat))
    y = R * dlat
    return x, y

def generate_aircraft_trajectory(aircraft, scenario, aip_data):
    """
    Početna logika (spirala + final + sletanje).
    Treba zameniti stvarnim segmentima iz AIP procedura!
    """

    # trenutno samo detektuje runway, ali ne koristi segmente 
    runway_procedures = []
    for rwy in aip_data['runways']:
        if '12R' in rwy['identifier'] and aircraft.arrival_direction in ['NORTH', 'EAST']:
            runway_procedures = rwy['procedures']['rnp']['approach_segments']
            break
        elif '30L' in rwy['identifier'] and aircraft.arrival_direction in ['SOUTH', 'WEST']:
            runway_procedures = rwy['procedures']['rnp']['approach_segments']
            break

    trajectory_points = []

    start_alt = 7000  # ft
    if aircraft.assigned_star and 'TISAK' in aircraft.assigned_star:
        start_lat, start_lon = 45.422, 20.227
    else:
        start_lat, start_lon = 44.892, 20.641

    trajectory_points.append({
        'lat': start_lat,
        'lon': start_lon,
        'alt': start_alt,
        'time': aircraft.arrival_time,
        'status': 'HOLDING'
    })

    num_points = 50
    for i in range(num_points):
        t = i / num_points
        angle = t * 2 * np.pi * 2
        radius = 0.02 * (1 - t)
        alt = start_alt * (1 - t**1.5)

        lat = start_lat + radius * np.cos(angle)
        lon = start_lon + radius * np.sin(angle)

        trajectory_points.append({
            'lat': lat,
            'lon': lon,
            'alt': alt,
            'time': aircraft.arrival_time + t * aircraft.instrument_time,
            'status': 'APPROACH'
        })

    runway_end_lat, runway_end_lon = config.REF_LAT, config.REF_LON

    trajectory_points.append({
        'lat': runway_end_lat,
        'lon': runway_end_lon,
        'alt': 50,
        'time': aircraft.landing_time - 30,
        'status': 'FINAL'
    })

    trajectory_points.append({
        'lat': runway_end_lat,
        'lon': runway_end_lon,
        'alt': 0,
        'time': aircraft.landing_time,
        'status': 'LANDED'
    })

    return {
        'aircraft_id': aircraft.id,
        'type': aircraft.type,
        'wake': aircraft.wake,
        'trajectory': trajectory_points,
        'arrival_time': aircraft.arrival_time,
        'landing_time': aircraft.landing_time,
        'wait_time': aircraft.waiting_start if hasattr(aircraft, 'waiting_start') else 0,
        'assigned_runway': aircraft.assigned_runway,
        'assigned_star': aircraft.assigned_star
    }
