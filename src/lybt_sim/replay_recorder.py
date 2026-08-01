# src/lybt_sim/replay_recorder.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Any

@dataclass
class ReplayTrack:
    id: str
    type: str = "UNKNOWN"
    keyframes: List[Dict[str, Any]] = field(default_factory=list)

class ReplayRecorder:
    def __init__(self):
        self.tracks: Dict[str, ReplayTrack] = {}

    def add(self, ac_id: str, t_sec: float, x: float, y: float, z: float,
            fuel: float, status: str, ac_type: str = "UNKNOWN"):
        tr = self.tracks.get(ac_id)
        if tr is None:
            tr = ReplayTrack(id=ac_id, type=ac_type)
            self.tracks[ac_id] = tr

        # keyframe format koji tvoj Three.js loader očekuje
        tr.keyframes.append({
            "t": float(t_sec),
            "x": float(x),
            "y": float(y),
            "z": float(z),
            "fuel": float(fuel) if fuel is not None else None,
            "status": status
        })

    def to_payload(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        aircraft = []
        for tr in self.tracks.values():
            aircraft.append({
                "id": tr.id,
                "type": tr.type,
                "keyframes": tr.keyframes
            })
        return {"meta": meta, "aircraft": aircraft}
