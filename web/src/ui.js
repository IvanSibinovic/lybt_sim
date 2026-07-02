// web/src/ui.js
export function setupUI({ durationSec, onSeek, onTogglePlay, onSetSpeed }) {
  const btn = document.getElementById("playPause");
  const slider = document.getElementById("slider");

  slider.max = String(durationSec);

  btn.addEventListener("click", () => onTogglePlay());
  slider.addEventListener("input", (e) => onSeek(Number(e.target.value)));

  // speed buttons
  document.querySelectorAll("button.spd").forEach(b => {
    b.addEventListener("click", () => {
      const s = Number(b.dataset.s || "1");
      if (onSetSpeed) onSetSpeed(s);
    });
  });

  return {
    setPlaying(isPlaying) { btn.textContent = isPlaying ? "Pause" : "Play"; },
    setTime(tSec) { slider.value = String(tSec); },
    setText({ tSec, phase, aircraftCount, speed }) {
      document.getElementById("time").textContent = `t=${tSec}s`;
      document.getElementById("phase").textContent =
        `Phase: ${phase} | aircraft=${aircraftCount ?? "?"} | ${speed ?? 1}x`;
    }
  };
}
