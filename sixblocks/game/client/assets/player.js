/* Interactive management seat: WebSocket /player + full render + HTML controls. */
"use strict";

(function () {
  const params = new URLSearchParams(window.location.search);
  const slot = params.get("slot") || "0";
  const token = params.get("token") || "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(proto + "//" + window.location.host +
    "/player?slot=" + encodeURIComponent(slot) + "&token=" + encodeURIComponent(token));

  const statsEl = document.getElementById("stats");
  const eventsEl = document.getElementById("events");
  const blocksEl = document.getElementById("blocks");
  const inspectorEl = document.getElementById("inspector");
  const logEl = document.getElementById("log");
  const finalEl = document.getElementById("final");
  const pickAction = document.getElementById("pick-action");
  const pickBlock = document.getElementById("pick-block");

  let welcome = null;
  let lastDashboard = null;

  const renderer = new SixBlocksRenderer("world", {
    onHover: function (hit) {
      if (hit && hit.kind === "block") inspectBlock(hit.obj.id, true);
    },
  });

  function log(text, cls) {
    const div = document.createElement("div");
    if (cls) div.className = cls;
    div.textContent = text;
    logEl.prepend(div);
    while (logEl.childNodes.length > 80) logEl.removeChild(logEl.lastChild);
  }

  function send(obj) { ws.send(JSON.stringify(obj)); }

  function inspectBlock(blockId, hoverOnly) {
    if (!hoverOnly) send({ type: "inspect", target_type: "block", target_id: blockId });
    pickBlock.value = blockId;
  }

  function renderDashboard(d) {
    lastDashboard = d;
    sbRenderStats(statsEl, d);
    sbRenderEvents(eventsEl, d);
    sbRenderBlocks(blocksEl, d, function (blockId) {
      send({ type: "inspect", target_type: "block", target_id: blockId });
      pickBlock.value = blockId;
    });
    renderer.setDay(d.day);
  }

  ws.onmessage = function (msg) {
    const m = JSON.parse(msg.data);
    switch (m.type) {
      case "welcome": {
        welcome = m;
        renderer.setWorld(m.world);
        pickAction.innerHTML = m.actions.map(function (a) {
          return '<option value="' + a.action + '">' + a.action.replace(/_/g, " ") +
            " — " + sbMoney(a.cost) + (a.daily_upkeep ? " +" + sbMoney(a.daily_upkeep) + "/day" : "") +
            "</option>";
        }).join("");
        pickBlock.innerHTML = m.blocks.map(function (b) {
          return '<option value="' + b.block_id + '">' + b.name + "</option>";
        }).join("");
        log("Connected. Seed " + m.seed + ".", "ok");
        break;
      }
      case "dashboard":
        renderDashboard(m);
        break;
      case "action_result":
        log("Day " + m.day + ": " + m.note + " (" + sbMoney(-m.cost) + ")", "ok");
        if (lastDashboard) {
          lastDashboard.budget = m.budget;
          lastDashboard.action_points_remaining = m.action_points_remaining;
          sbRenderStats(statsEl, lastDashboard);
        }
        break;
      case "day_advanced":
        log("— Day " + m.day + " begins —");
        (m.notes || []).slice(-4).forEach(function (n) { log(n); });
        break;
      case "inspection":
        inspectorEl.textContent = JSON.stringify(m.data != null ? m.data : m, null, 2);
        break;
      case "error":
        log(m.code + ": " + m.message, "err");
        break;
      case "episode_finished":
      case "final": {
        const results = m.results;
        if (results) sbRenderFinal(finalEl, results);
        log("Episode complete.", "ok");
        document.getElementById("end-day").disabled = true;
        document.getElementById("do-action").disabled = true;
        break;
      }
      default:
        if (m.target_type) inspectorEl.textContent = JSON.stringify(m, null, 2);
    }
    if (m.frame) renderer.setFrame(m.frame);
    if (m.type === "dashboard" && welcome) {
      // Live view uses the latest daily frame shape for block tinting.
      renderer.setFrame({
        blocks: (m.blocks || []).map(function (b) {
          return Object.assign({}, b, { conditions: b.active_conditions || [] });
        }),
        events: m.events || [],
      });
    }
  };

  ws.onclose = function () { log("Connection closed.", "err"); };

  document.getElementById("do-action").addEventListener("click", function () {
    send({ type: "action", action: pickAction.value, target_id: pickBlock.value });
  });
  document.getElementById("do-inspect").addEventListener("click", function () {
    send({ type: "inspect", target_type: "block", target_id: pickBlock.value });
  });
  document.getElementById("end-day").addEventListener("click", function () {
    send({ type: "end_day" });
  });
})();
