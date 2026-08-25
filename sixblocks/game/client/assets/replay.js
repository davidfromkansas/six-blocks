/* Replay: loads the saved episode over /replay and scrubs through daily frames. */
"use strict";

(function () {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(proto + "//" + window.location.host + "/replay");
  const renderer = new SixBlocksRenderer("world", {});
  const scrub = document.getElementById("scrub");
  const playBtn = document.getElementById("play");
  const dayLabel = document.getElementById("daylabel");

  let replay = null;
  let index = 0;
  let playing = false;
  let timer = null;

  function show(i) {
    if (!replay || !replay.frames.length) return;
    index = Math.max(0, Math.min(replay.frames.length - 1, i));
    scrub.value = index;
    const frame = replay.frames[index];
    dayLabel.textContent = "Day " + frame.day + " / " + replay.frames.length;
    renderer.setDay(frame.day);
    renderer.setFrame(frame);
    const m = frame.metrics || {};
    sbRenderStats(document.getElementById("stats"), {
      day: frame.day, total_days: replay.frames.length,
      budget: frame.budget, action_points_remaining: 0,
      daily_upkeep: frame.upkeep_per_day,
      average_mood: m.average_mood || 0, health: m.average_health || 0,
      mobility: m.mobility || 0, cleanliness: m.cleanliness || 0,
      business_health: m.business_health || 0,
      average_rent_burden: m.average_rent_burden || 0,
      median_rent: m.median_rent || 0, population: m.population || 0,
    });
    document.getElementById("events").innerHTML =
      (frame.events || []).map((e) => '<div class="event">' + (e.headline || e.kind) + "</div>").join("") +
      (frame.notes || []).map((n) => '<div class="note">' + n + "</div>").join("");
    document.getElementById("actions").innerHTML =
      (frame.actions || []).map((a) =>
        '<div class="note">' + a.action.replace(/_/g, " ") + " @ " + a.target_id +
        " (" + sbMoney(-a.cost) + ")</div>").join("") || '<div class="note">No interventions</div>';
    if (index === replay.frames.length - 1 && replay.results) {
      sbRenderFinal(document.getElementById("final"), replay.results);
    }
  }

  function setPlaying(v) {
    playing = v;
    playBtn.textContent = playing ? "❚❚ Pause" : "▶ Play";
    if (timer) { clearInterval(timer); timer = null; }
    if (playing) {
      timer = setInterval(function () {
        if (index >= replay.frames.length - 1) { setPlaying(false); return; }
        show(index + 1);
      }, 900);
    }
  }

  ws.onmessage = function (msg) {
    const m = JSON.parse(msg.data);
    if (m.type !== "replay") return;
    replay = m;
    renderer.setWorld(m.world);
    scrub.max = Math.max(0, m.frames.length - 1);
    show(0);
    setPlaying(true);
  };

  scrub.addEventListener("input", function () { setPlaying(false); show(parseInt(scrub.value, 10)); });
  playBtn.addEventListener("click", function () { setPlaying(!playing); });
})();
