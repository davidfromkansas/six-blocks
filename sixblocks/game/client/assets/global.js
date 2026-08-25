/* Spectator: renders live state pushed over /global. */
"use strict";

(function () {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(proto + "//" + window.location.host + "/global");
  const renderer = new SixBlocksRenderer("world", {});
  let haveWorld = false;

  ws.onmessage = function (msg) {
    const m = JSON.parse(msg.data);
    if (m.type !== "state") return;
    if (!haveWorld && m.world) {
      renderer.setWorld(m.world);
      haveWorld = true;
    }
    renderer.setDay(m.day);
    if (m.frame) renderer.setFrame(m.frame);
    if (m.dashboard) {
      sbRenderStats(document.getElementById("stats"), m.dashboard);
      sbRenderEvents(document.getElementById("events"), m.dashboard);
      sbRenderBlocks(document.getElementById("blocks"), m.dashboard, null);
    }
    if (m.finished && m.frame && m.frame.results) {
      sbRenderFinal(document.getElementById("final"), m.frame.results);
    }
  };
})();
