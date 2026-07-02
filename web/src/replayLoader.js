//  web/src/replayLoader.js

export async function loadReplay(url = "/replay.json") {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load replay: ${res.status}`);
  return await res.json();
}

// linear interpolation between two keyframes
export function lerp(a, b, t) { return a + (b - a) * t; }

export function sampleAircraftAtTime(ac, tSec) {
  const kf = ac.keyframes;
  if (!kf || kf.length === 0) return null;
  if (tSec <= kf[0].t) return kf[0];
  if (tSec >= kf[kf.length - 1].t) return kf[kf.length - 1];

  // find segment (simple scan; can be optimized with pointer)
  let i = 0;
  while (i < kf.length - 1 && !(kf[i].t <= tSec && tSec <= kf[i+1].t)) i++;

  const a = kf[i], b = kf[i+1];
  const span = b.t - a.t || 1;
  const u = (tSec - a.t) / span;

  return {
    t: tSec,
    x: lerp(a.x, b.x, u),
    y: lerp(a.y, b.y, u),
    z: lerp(a.z, b.z, u),
    fuel: lerp(a.fuel, b.fuel, u),
    status: (u < 0.5 ? a.status : b.status)
  };
}
