// web/src/main.js
import "./style.css";

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { loadReplay, sampleAircraftAtTime } from "./replayLoader.js";
import { setupUI } from "./ui.js";

const SCALE = 1.0; // 1 unit = 1 meter

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0f14);

const camera = new THREE.PerspectiveCamera(
  60,
  window.innerWidth / window.innerHeight,
  10,
  5_000_000
);
camera.up.set(0, 0, 1);
camera.position.set(0, -8000, 5000);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

// OrbitControls (radi sada, jer je npm import)
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.update();

// lights
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const dir = new THREE.DirectionalLight(0xffffff, 0.8);
dir.position.set(5000, -5000, 8000);
scene.add(dir);

// ground
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(20000, 20000),
  new THREE.MeshStandardMaterial({ color: 0x0e131a, roughness: 1.0 })
);
ground.position.z = 0.0;
scene.add(ground);

// grid
const grid = new THREE.GridHelper(40000, 80, 0x1a2430, 0x1a2430);
grid.rotation.set(Math.PI / 2, 0, 0); // XY plane, Z-up
grid.position.z = 0;
grid.material.depthWrite = false;
grid.renderOrder = 1;
scene.add(grid);

function makeAircraftMesh() {
  const scale = 2.5; // probaj 2.0 ili 2.5
  const geom = new THREE.ConeGeometry(180 / scale, 650 / scale, 12);
  geom.rotateZ(-Math.PI / 2);

  const mat = new THREE.MeshStandardMaterial({ color: 0x4aa3ff });
  return new THREE.Mesh(geom, mat);
}

function statusColor(status) {
  if (status === "FINAL") return 0xffffff;
  if (status === "APPROACH") return 0x4aa3ff;
  if (status === "HOLDING") return 0xffc857;
  if (status === "LANDED") return 0x7cff7c;
  return 0x4aa3ff;
}

let replay;
const aircraftMeshes = new Map();

let tSec = 0;
let playing = false;
let timeScale = 1;

// trails
const TRAIL_STEP_SEC = 1.5;
const TRAIL_MAX_POINTS = 300;
const TRAIL_JUMP_RESET_M = 1500; // ako avion "skoči" > 1.5km, resetuj trail

const trails = new Map(); // acId -> { line, points, lastT }

function setFogIFR(_isIFR) {
  scene.fog = null;
}

function parseAipCoord(s) {
  const parts = s.trim().split(/\s+/);
  const latStr = parts[0];
  const lonStr = parts[1];

  function dmsToDeg(v) {
    const hemi = v.slice(-1).toUpperCase();     // N/S/E/W
    const num  = v.slice(0, -1);

    const isLon = (hemi === "E" || hemi === "W");
    const degLen = isLon ? 3 : 2;

    const deg = parseInt(num.slice(0, degLen), 10);
    const min = parseInt(num.slice(degLen, degLen + 2), 10);
    const sec = parseFloat(num.slice(degLen + 2));

    let out = deg + min / 60 + sec / 3600;
    if (hemi === "S" || hemi === "W") out *= -1;
    return out;
  }

  return { lat: dmsToDeg(latStr), lon: dmsToDeg(lonStr) };
}

function latLonToXY(lat, lon, refLat, refLon) {
  const R = 6371000;
  const phi = (lat * Math.PI) / 180;
  const phi0 = (refLat * Math.PI) / 180;
  const lam = (lon * Math.PI) / 180;
  const lam0 = (refLon * Math.PI) / 180;

  const x = (lam - lam0) * Math.cos(phi0) * R;
  const y = (phi - phi0) * R;
  return { x, y };
}

function phaseAt(t) {
  if (!replay?.meta) return "VFR";
  return t < replay.meta.t_change_sec ? "VFR" : "IFR";
}

function ensureTrail(acId) {
  let tr = trails.get(acId);
  if (tr) return tr;

  const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0)]);
  const mat = new THREE.LineBasicMaterial({
    color: 0x00ff99,
    transparent: true,
    opacity: 0.9,
    depthTest: false,
    depthWrite: false
  });

  const line = new THREE.Line(geo, mat);
  line.frustumCulled = false;
  line.renderOrder = 10;
  scene.add(line);

  tr = { line, points: [], lastT: -1e9, lastPos: null };
  trails.set(acId, tr);
  return tr;
}

function runwayStagger(_identifier) {
  return { lat: 0, lon: 0 };
}

function orderedThresholds(rw) {
  const thr = rw.thresholds || [];
  if (thr.length < 2) return null;

  const startEnd = (rw.identifier || "").split("/")[0];
  const i0 = thr.findIndex(t => t.end === startEnd);
  const a = thr[i0 >= 0 ? i0 : 0];
  const b = thr[i0 >= 0 ? (i0 === 0 ? 1 : 0) : 1];
  return [a, b];
}

function drawRunwaysFromLayout(layout, refLat, refLon) {
  const group = new THREE.Group();
  group.name = "RUNWAYS";
  scene.add(group);

  for (const rw of (layout.runways || [])) {
    const len = rw.dimensions_m?.length ?? 2500;
    const wid = rw.dimensions_m?.width ?? 45;

    const pair = orderedThresholds(rw);
    if (!pair) continue;
    const [thrA, thrB] = pair;

    const pA = parseAipCoord(thrA.coordinates);
    const pB = parseAipCoord(thrB.coordinates);
    const a = latLonToXY(pA.lat, pA.lon, refLat, refLon);
    const b = latLonToXY(pB.lat, pB.lon, refLat, refLon);

    const midX = (a.x + b.x) / 2;
    const midY = (a.y + b.y) / 2;

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const ang = Math.atan2(dy, dx);

    const st = runwayStagger(rw.identifier);

    const tx = Math.cos(ang);
    const ty = Math.sin(ang);
    const nx = -Math.sin(ang);
    const ny = Math.cos(ang);

    const offX = nx * st.lat + tx * st.lon;
    const offY = ny * st.lat + ty * st.lon;

    function addThresholdMarker(x, y, colorHex) {
      const g = new THREE.SphereGeometry(18, 16, 16);
      const m = new THREE.MeshStandardMaterial({
        color: colorHex,
        emissive: colorHex,
        emissiveIntensity: 0.6
      });
      const s = new THREE.Mesh(g, m);
      s.position.set(x, y, 8);
      group.add(s);
    }

    addThresholdMarker(a.x + offX, a.y + offY, 0x00ff99);
    addThresholdMarker(b.x + offX, b.y + offY, 0xffcc00);

    const mat = new THREE.MeshStandardMaterial({
      color: 0x7a7a7a,
      roughness: 0.7,
      metalness: 0.0,
      emissive: 0x222222,
      emissiveIntensity: 0.8
    });

    mat.polygonOffset = true;
    mat.polygonOffsetFactor = -2;
    mat.polygonOffsetUnits = -2;

    const runway = new THREE.Mesh(new THREE.PlaneGeometry(len, wid), mat);
    runway.rotation.z = ang;
    runway.position.set(midX + offX, midY + offY, 1.5);
    runway.renderOrder = 2;
    group.add(runway);

    const edgeMat = new THREE.LineBasicMaterial({ color: 0xffffff });
    const edgeGeo = new THREE.EdgesGeometry(new THREE.PlaneGeometry(len, wid));
    const edges = new THREE.LineSegments(edgeGeo, edgeMat);
    edges.rotation.z = ang;
    edges.position.set(midX + offX, midY + offY, 4);
    group.add(edges);

    const half = len / 2;
    const x1 = midX - Math.cos(ang) * half;
    const y1 = midY - Math.sin(ang) * half;
    const x2 = midX + Math.cos(ang) * half;
    const y2 = midY + Math.sin(ang) * half;

    const c1 = new THREE.Vector3(x1 + offX, y1 + offY, 3.5);
    const c2 = new THREE.Vector3(x2 + offX, y2 + offY, 3.5);

    const lineGeo = new THREE.BufferGeometry().setFromPoints([c1, c2]);
    const lineMat = new THREE.LineBasicMaterial({ color: 0xffffff });
    const line = new THREE.Line(lineGeo, lineMat);
    line.renderOrder = 3;
    group.add(line);

    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(2, 2, 120, 10),
      new THREE.MeshStandardMaterial({ color: 0x44607a })
    );
    pole.position.set(midX + offX, midY + offY, 60);
    pole.renderOrder = 4;
    group.add(pole);

    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(0,0,0,0.65)";
    ctx.fillRect(0, 0, 512, 128);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 54px sans-serif";
    ctx.fillText(rw.identifier, 20, 85);

    const tex = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: tex, transparent: true })
    );
    sprite.scale.set(900, 240, 1);
    sprite.position.set(midX + offX, midY + offY, 160);
    sprite.renderOrder = 5;
    group.add(sprite);
  }

  return group;
}

function buildRunwayCache(layout, refLat, refLon) {
  const out = {};
  for (const rw of (layout.runways || [])) {
    const thr = rw.thresholds || [];
    if (thr.length < 2) continue;

    const A = parseAipCoord(thr[0].coordinates);
    const B = parseAipCoord(thr[1].coordinates);
    const a = latLonToXY(A.lat, A.lon, refLat, refLon);
    const b = latLonToXY(B.lat, B.lon, refLat, refLon);

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const ang = Math.atan2(dy, dx);

    const st = runwayStagger(rw.identifier);

    const tx = Math.cos(ang);
    const ty = Math.sin(ang);
    const nx = -Math.sin(ang);
    const ny = Math.cos(ang);

    const offX = nx * st.lat + tx * st.lon;
    const offY = ny * st.lat + ty * st.lon;

    out[thr[0].end] = {
      x: a.x + offX,
      y: a.y + offY,
      z: 0,
      pairEnd: thr[1].end,
      pairXY: { x: b.x + offX, y: b.y + offY }
    };
    out[thr[1].end] = {
      x: b.x + offX,
      y: b.y + offY,
      z: 0,
      pairEnd: thr[0].end,
      pairXY: { x: a.x + offX, y: a.y + offY }
    };
  }
  return out;
}

function patchLandingKeyframes(ac, rwCache, landingEnd = "12L") {
  const kf = ac.keyframes || [];
  if (kf.length < 2) return;

  const hasFinalOrLanded = kf.some(p => p.status === "FINAL" || p.status === "LANDED");
  if (hasFinalOrLanded) return;

  const thr = rwCache[landingEnd];
  if (!thr) return;

  const last = kf[kf.length - 1];

  const tHoldEnd = Math.max(last.t - 120, kf[0].t + 30);
  const tTouch = tHoldEnd + 90;
  const tRollEnd = tTouch + 35;

  const other = thr.pairXY;
  const dx = other.x - thr.x;
  const dy = other.y - thr.y;
  const L = Math.hypot(dx, dy) || 1;
  const ux = dx / L,
    uy = dy / L;

  const finalDist = 5000;
  const gsAngle = THREE.MathUtils.degToRad(3);
  const finalAlt = Math.tan(gsAngle) * finalDist + 30;

  const finalStart = {
    x: thr.x - ux * finalDist,
    y: thr.y - uy * finalDist,
    z: finalAlt
  };

  const rollout = {
    x: thr.x + ux * 800,
    y: thr.y + uy * 800,
    z: 0
  };

  ac.keyframes = [
    ...kf,
    {
      t: tHoldEnd,
      x: last.x,
      y: last.y,
      z: Math.max(last.z, finalAlt + 300),
      fuel: last.fuel ?? 1,
      status: "APPROACH"
    },
    {
      t: tHoldEnd + 5,
      x: finalStart.x,
      y: finalStart.y,
      z: finalStart.z,
      fuel: last.fuel ?? 1,
      status: "FINAL"
    },
    { t: tTouch, x: thr.x, y: thr.y, z: 5, fuel: last.fuel ?? 1, status: "FINAL" },
    {
      t: tTouch + 3,
      x: thr.x,
      y: thr.y,
      z: 0,
      fuel: last.fuel ?? 1,
      status: "LANDED"
    },
    { t: tRollEnd, x: rollout.x, y: rollout.y, z: 0, fuel: last.fuel ?? 1, status: "LANDED" }
  ];

  ac.keyframes.sort((a, b) => a.t - b.t);
}

function renderFrame() {
  const phase = phaseAt(tSec);
  setFogIFR(phase === "IFR");

  for (const ac of replay.aircraft) {
    const s = sampleAircraftAtTime(ac, tSec);
    if (!s) continue;

    let mesh = aircraftMeshes.get(ac.id);
    if (!mesh) {
      mesh = makeAircraftMesh();
      scene.add(mesh);
      aircraftMeshes.set(ac.id, mesh);
    }

    let z = s.z * SCALE + 10;
    if (s.status === "HOLDING") {
      const slot = (Number(ac.id) || 0) % 5;
      z += slot * 120;
    }
    mesh.position.set(s.x * SCALE, s.y * SCALE, z);

    if (mesh.userData.prevPos) {
      const dx = mesh.position.x - mesh.userData.prevPos.x;
      const dy = mesh.position.y - mesh.userData.prevPos.y;
      const heading = Math.atan2(dy, dx);
      mesh.rotation.set(0, 0, heading);
    }
    mesh.userData.prevPos = mesh.position.clone();

    const tr = ensureTrail(ac.id);

    // 1) detekcija skoka i čuvanje lastPos
    const cur = mesh.position.clone().add(new THREE.Vector3(0,0,3));

    if (tr.lastPos) {
      const jump = cur.distanceTo(tr.lastPos);
      if (jump > TRAIL_JUMP_RESET_M) {
        tr.points = [];
        tr.lastT = -1e9;
      }
    }

    // 2) dodaj u trail *PRETHODNU* poziciju (da rep bude iza)
    if (tSec - tr.lastT >= TRAIL_STEP_SEC) {
      tr.lastT = tSec;

      // ako je prvi put, samo postavi lastPos (ne crtamo ništa)
      if (!tr.lastPos) {
        tr.lastPos = cur.clone();
      } else {
        tr.points.push(tr.lastPos.clone()); // <-- ključna promena: guramo PRETHODNU
        if (tr.points.length > TRAIL_MAX_POINTS) tr.points.shift();

        tr.line.geometry.dispose();
        tr.line.geometry = new THREE.BufferGeometry().setFromPoints(tr.points);
        tr.line.visible = tr.points.length >= 2; // linija ima smisla tek od 2 tačke
      }
    }

    // 3) update lastPos na kraju
    tr.lastPos = cur;

    mesh.material.color.setHex(statusColor(s.status));
    tr.line.material.color.setHex(statusColor(s.status));

    if (s.fuel !== null && s.fuel <= 0) {
      mesh.visible = (Math.floor(performance.now() / 200) % 2) === 0;
    } else {
      mesh.visible = true;
    }
    if (ac.id === replay.aircraft[0].id) console.log("AC sample:", s);
  }

  hud.setText({
    tSec: Math.floor(tSec),
    phase,
    aircraftCount: replay.aircraft.length,
    speed: timeScale
  });

  controls.update();
  renderer.render(scene, camera);
}

const hud = setupUI({
  durationSec: 3600,
  onSeek: v => {
    tSec = v;
    for (const tr of trails.values()) {
      tr.points = [];
      tr.lastT = -1e9;
      tr.line.visible = false;
      tr.line.geometry.dispose();
      tr.line.geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0,0,0)]);
    }
    renderFrame();
  },
  onTogglePlay: () => {
    playing = !playing;
    hud.setPlaying(playing);
  },
  onSetSpeed: s => {
    timeScale = s;
  }
});

let last = performance.now();
function tick(now = performance.now()) {
  const dt = (now - last) / 1000;
  last = now;

  if (playing) {
    tSec = Math.min(3600, tSec + dt * timeScale);
    hud.setTime(Math.floor(tSec));
    renderFrame();
    if (tSec >= 3600) {
      playing = false;
      hud.setPlaying(false);
    }
  } else {
    // i kad je pauza, controls damping treba update
    controls.update();
    renderer.render(scene, camera);
  }

  requestAnimationFrame(tick);
}

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// debug helpers
scene.add(new THREE.AxesHelper(5000));
const dbg = new THREE.Mesh(
  new THREE.BoxGeometry(500, 500, 500),
  new THREE.MeshStandardMaterial({ color: 0xff00ff, emissive: 0xff00ff, emissiveIntensity: 1 })
);
dbg.position.set(0, 0, 250);
dbg.frustumCulled = false;
scene.add(dbg);

function focusCameraOnBox(box) {
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);

  if (!isFinite(size.x) || (size.x === 0 && size.y === 0 && size.z === 0)) {
    console.warn("focusCameraOnBox: empty box", box);
    return;
  }

  const maxDim = Math.max(size.x, size.y, size.z);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  let dist = (maxDim / 2) / Math.tan(fov / 2);
  dist *= 1.6;

  camera.position.set(center.x, center.y - dist, center.z + dist * 0.55);
  camera.lookAt(center);
  camera.updateProjectionMatrix();

  // bitno za OrbitControls:
  controls.target.copy(center);
  controls.update();

  console.log("RUNWAY box size:", size, "center:", center);
}


(async function boot() {
  try {
    // Vite: public/ => root
    replay = await loadReplay("/replay.json");
    const layout = await (await fetch("/layout.json")).json();

    const rwyGroup = drawRunwaysFromLayout(layout, replay.meta.ref_lat, replay.meta.ref_lon);

    // DEBUG: proveri da li layout uopšte ima runway-e
    console.log("layout.runways:", layout.runways?.length, layout.runways);

    const box = new THREE.Box3().setFromObject(rwyGroup);
    box.expandByScalar(1500); // malo “lufta”
    focusCameraOnBox(box);

    const rwCache = buildRunwayCache(layout, replay.meta.ref_lat, replay.meta.ref_lon);

    for (const ac of replay.aircraft || []) {
      patchLandingKeyframes(ac, rwCache, "12L");
    }

    if (!replay.aircraft || replay.aircraft.length === 0) {
      console.warn("Replay has no aircraft. Using demo aircraft.");
      replay.aircraft = [
        {
          id: "DEMO-1",
          keyframes: [
            { t: 0, x: -2000, y: -500, z: 250, fuel: 1, status: "APPROACH" },
            { t: 900, x: -500, y: 0, z: 220, fuel: 1, status: "APPROACH" },
            { t: 1800, x: 0, y: 0, z: 180, fuel: 1, status: "FINAL" },
            { t: 2400, x: 600, y: 0, z: 80, fuel: 1, status: "FINAL" },
            { t: 2700, x: 900, y: 0, z: 10, fuel: 1, status: "LANDED" },
            { t: 3600, x: 1100, y: 0, z: 10, fuel: 1, status: "LANDED" }
          ]
        }
      ];
    }

    hud.setPlaying(false);
    renderFrame();
    tick();
  } catch (err) {
    console.error(err);
    document.getElementById("phase").textContent = "Phase: ERROR (see console)";
    document.getElementById("time").textContent = String(err);
  }
})();