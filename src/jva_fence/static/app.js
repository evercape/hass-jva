const connectPanel = document.querySelector("#connect-panel");
const statusPanel = document.querySelector("#status-panel");
const connectError = document.querySelector("#connect-error");
const statusError = document.querySelector("#status-error");
const zonesEl = document.querySelector("#zones");
const excerptEl = document.querySelector("#excerpt");
const probeEl = document.querySelector("#probe");
const clearButton = document.querySelector("#clear-alarms");
const envButton = document.querySelector("#env-connect");

let source = null;

async function readError(response) {
  try {
    const body = await response.json();
    return body.detail || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

function showError(node, message) {
  node.hidden = !message;
  node.textContent = message || "";
}

function voltageLabel(zone) {
  if (zone.reading) return `Return ${zone.reading}`;
  if (zone.return_voltage_kv == null) return "Return —";
  const number = Number(zone.return_voltage_kv).toFixed(1);
  return `Return ${number} kV`;
}

function stateWord(state) {
  if (state === "ok") return "OK";
  if (state === "error") return "Error";
  return "Unknown";
}

function render(payload) {
  source = payload.source;
  connectPanel.hidden = true;
  statusPanel.hidden = false;
  document.querySelector("#source-label").textContent =
    payload.source === "demo" ? "Sample page" : `Live · ${payload.host}`;
  document.querySelector("#page-title").textContent = payload.page.title || "Zones";
  clearButton.hidden = !payload.page.has_clear_alarms;
  excerptEl.textContent = payload.excerpt || "";
  zonesEl.replaceChildren();
  for (const zone of payload.page.zones) {
    zonesEl.append(renderZone(zone));
  }
  if (payload.page.zones.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "Signed in, but no zones were found in the HTML. The page text below is what the controller returned.";
    zonesEl.append(empty);
  }
  if (payload.api_probe) renderProbe(payload.api_probe);
  const note = document.querySelector("#refresh-note");
  const next = (payload.next_frames || [])
    .map((url) => url.replace(/^https?:\/\/[^/]+/, ""))
    .join(", ");
  note.textContent = payload.refreshed_at
    ? `Updated ${payload.refreshed_at}${next ? ` · next ${next}` : ""}`
    : "";
}

function renderZone(zone) {
  const card = document.createElement("article");
  card.className = "zone";
  const head = document.createElement("div");
  head.className = "zone-head";
  const title = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = zone.name;
  const mode = document.createElement("div");
  mode.className = "mode";
  mode.textContent = zone.mode.replaceAll("_", " ");
  title.append(heading, mode);
  const voltage = document.createElement("div");
  voltage.className = `voltage ${zone.voltage_state}`;
  voltage.textContent = `${voltageLabel(zone)} · ${stateWord(zone.voltage_state)}`;
  head.append(title, voltage);
  card.append(head);

  if (zone.alarms.length) {
    const alarms = document.createElement("div");
    alarms.className = "alarms";
    for (const alarm of zone.alarms) {
      const chip = document.createElement("span");
      chip.className = alarm.active ? "chip on" : "chip";
      const mark = alarm.active == null ? "unknown" : alarm.active ? "active" : "clear";
      chip.textContent = `${alarm.name}: ${mark}`;
      alarms.append(chip);
    }
    card.append(alarms);
  }

  const actions = document.createElement("div");
  actions.className = "actions";
  for (const mode of ["armed", "disarmed", "low_power"]) {
    if (!zone.modes.includes(mode)) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = mode === "low_power" ? "Low power" : mode[0].toUpperCase() + mode.slice(1);
    const current = zone.mode === mode;
    button.disabled = current;
    button.className = current ? "primary" : "";
    button.setAttribute("aria-pressed", current ? "true" : "false");
    button.addEventListener("click", () => changeMode(zone, mode));
    actions.append(button);
  }
  card.append(actions);
  return card;
}

async function changeMode(zone, mode) {
  if (source === "live") {
    const label = mode.replace("_", " ");
    const ok = window.confirm(`Set ${zone.name} to ${label} on the live fence controller?`);
    if (!ok) return;
  }
  showError(statusError, "");
  const response = await fetch(`/api/zones/${encodeURIComponent(zone.zone_id)}/mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!response.ok) {
    showError(statusError, await readError(response));
    return;
  }
  render(await response.json());
}

function renderProbe(probe) {
  probeEl.hidden = false;
  probeEl.replaceChildren();
  const summary = document.createElement("p");
  const strong = document.createElement("strong");
  strong.textContent = probe.api_found ? "Structured API found. " : "No API found. ";
  summary.append(strong, document.createTextNode(probe.summary || ""));
  const table = document.createElement("table");
  const head = document.createElement("tr");
  for (const label of ["Status", "Kind", "URL"]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    head.append(cell);
  }
  const thead = document.createElement("thead");
  thead.append(head);
  const tbody = document.createElement("tbody");
  for (const item of probe.checked || []) {
    const row = document.createElement("tr");
    for (const value of [item.status ?? "", item.kind || "", item.url || ""]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    tbody.append(row);
  }
  table.append(thead, tbody);
  probeEl.append(summary, table);
}

async function connect(body) {
  showError(connectError, "");
  const response = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    showError(connectError, await readError(response));
    return;
  }
  render(await response.json());
}

document.querySelector("#live-form").addEventListener("submit", (event) => {
  event.preventDefault();
  connect({
    mode: "live",
    host: document.querySelector("#host").value,
    username: document.querySelector("#username").value,
    password: document.querySelector("#password").value,
  });
});

document.querySelector("#demo-connect").addEventListener("click", () => {
  connect({ mode: "demo" });
});

envButton.addEventListener("click", () => {
  connect({ mode: "live", use_env: true });
});

document.querySelector("#refresh").addEventListener("click", async () => {
  const button = document.querySelector("#refresh");
  button.disabled = true;
  button.textContent = "Refreshing…";
  showError(statusError, "");
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) {
      showError(statusError, await readError(response));
      return;
    }
    render(await response.json());
  } finally {
    button.disabled = false;
    button.textContent = "Refresh";
  }
});

document.querySelector("#investigate").addEventListener("click", async () => {
  const response = await fetch("/api/investigate");
  if (!response.ok) {
    showError(statusError, await readError(response));
    return;
  }
  renderProbe(await response.json());
});

clearButton.addEventListener("click", async () => {
  if (source === "live" && !window.confirm("Clear alarm memory on the live controller?")) return;
  const response = await fetch("/api/alarms/clear", { method: "POST" });
  if (!response.ok) {
    showError(statusError, await readError(response));
    return;
  }
  render(await response.json());
});

document.querySelector("#disconnect").addEventListener("click", async () => {
  await fetch("/api/session", { method: "DELETE" });
  source = null;
  statusPanel.hidden = true;
  connectPanel.hidden = false;
  probeEl.hidden = true;
  showError(statusError, "");
});

fetch("/api/config")
  .then((response) => response.json())
  .then((config) => {
    if (config.host) document.querySelector("#host").value = config.host;
    if (config.username) document.querySelector("#username").value = config.username;
    envButton.hidden = !config.has_env_credentials;
  });
