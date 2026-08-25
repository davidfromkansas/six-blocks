/* Shared HTML dashboard rendering for player / global / replay clients. */
"use strict";

function sbClass(v, lo, hi) { return v >= hi ? "good" : v >= lo ? "warn" : "bad"; }
function sbMoney(v) {
  const sign = v < 0 ? "-" : "";
  return sign + "$" + Math.abs(Math.round(v)).toLocaleString();
}
function sbBar(v, cls) {
  return '<div class="bar"><i class="' + cls + '" style="width:' + Math.max(0, Math.min(100, v)) +
    '%;background:currentColor"></i></div>';
}
function sbStat(k, v, cls, bar) {
  return '<div class="stat"><div class="k">' + k + '</div><div class="v ' + (cls || "") + '">' + v +
    (bar == null ? "" : sbBar(bar, cls)) + "</div></div>";
}

function sbRenderStats(el, d) {
  el.innerHTML =
    sbStat("Day", d.day + " / " + d.total_days, "", null) +
    sbStat("Budget", sbMoney(d.budget), d.budget > 60000 ? "good" : d.budget > 0 ? "warn" : "bad", null) +
    sbStat("Actions left", d.action_points_remaining, d.action_points_remaining ? "good" : "warn", null) +
    sbStat("Daily upkeep", sbMoney(d.daily_upkeep || 0), "", null) +
    sbStat("Mood", d.average_mood.toFixed(1), sbClass(d.average_mood, 45, 60), d.average_mood) +
    sbStat("Health", d.health.toFixed(1), sbClass(d.health, 45, 60), d.health) +
    sbStat("Mobility", d.mobility.toFixed(1), sbClass(d.mobility, 45, 60), d.mobility) +
    sbStat("Cleanliness", d.cleanliness.toFixed(1), sbClass(d.cleanliness, 45, 60), d.cleanliness) +
    sbStat("Business", d.business_health.toFixed(1), sbClass(d.business_health, 45, 60), d.business_health) +
    sbStat("Rent burden", (d.average_rent_burden * 100).toFixed(0) + "%",
      d.average_rent_burden < 0.33 ? "good" : d.average_rent_burden < 0.42 ? "warn" : "bad", null) +
    sbStat("Median rent", sbMoney(d.median_rent), "", null) +
    sbStat("Population", d.population, "", null);
}

function sbRenderEvents(el, d) {
  const events = d.events || [];
  const alerts = d.alerts || [];
  const notes = d.recent_changes || [];
  el.innerHTML =
    (events.length
      ? events.map((e) => '<div class="event">' + (e.headline || e.kind) +
          (e.days_remaining != null ? " (" + e.days_remaining + "d left)" : "") + "</div>").join("")
      : '<div class="note">No active events</div>') +
    alerts.map((a) => '<div class="alert">' + a + "</div>").join("") +
    notes.slice(-6).map((n) => '<div class="note">' + n + "</div>").join("");
}

function sbRenderBlocks(el, d, onclick) {
  el.innerHTML = (d.blocks || []).map((b) => {
    const mood = b.average_mood == null ? 55 : b.average_mood;
    const color = mood > 60 ? "var(--good)" : mood > 45 ? "var(--warn)" : "var(--bad)";
    const need = typeof b.worst_need === "string" ? b.worst_need.replace(/_/g, " ") : "";
    return '<div class="blockrow" data-block="' + b.block_id + '">' +
      '<span class="dot" style="background:' + color + '"></span>' +
      '<span class="nm">' + b.name + "</span>" +
      '<span class="need">' + need + "</span></div>";
  }).join("");
  if (onclick) {
    el.querySelectorAll(".blockrow").forEach((row) =>
      row.addEventListener("click", () => onclick(row.dataset.block)));
  }
}

function sbRenderFinal(el, results) {
  const comps = results.components || {};
  el.innerHTML = '<div class="final"><div class="k">FINAL SCORE</div>' +
    '<div class="score">' + results.score.toFixed(1) + " / 100</div>" +
    Object.keys(comps).sort().map((k) =>
      '<div class="kv"><span>' + k.replace(/_/g, " ") + "</span><span>" +
      comps[k].toFixed(1) + "</span></div>").join("") +
    "</div>";
}
