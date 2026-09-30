/* Presentation only: Python supplies every node position and call-depth layer. */
"use strict";
const vscode = acquireVsCodeApi();
const svg = document.getElementById("graph");
const scene = document.getElementById("scene");
const controls = Object.fromEntries(["root", "depth", "callers", "fit", "zoomIn", "zoomOut"]
  .map(id => [id, document.getElementById(id)]));
const traceControls = Object.fromEntries(["previous", "over", "into", "out", "reset"]
  .map(action => [action, document.getElementById(`trace${action[0].toUpperCase()}${action.slice(1)}`)]));
const traceToolbar = document.getElementById("traceToolbar");
const traceButtons = document.getElementById("traceButtons");
const traceOverflow = document.getElementById("traceOverflow");
const traceMenu = document.getElementById("traceMenu");
const playbackButtons = [document.getElementById("traceLoad"), ...Object.values(traceControls)];
let state;
let viewport;
let drawnVersion;
let drawnTrace;
let drag;
let moved = false;

/** Partition measured controls without copying buttons or altering backend availability. */
function traceLayout(buttons, width, overflowWidth, gap = 4) {
  const total = buttons.reduce((sum, item) => sum + item.width, 0) + Math.max(0, buttons.length - 1) * gap;
  if (total <= width) return { visible: buttons, overflow: [] };
  const available = Math.max(0, width - overflowWidth - gap);
  let used = 0, count = 0;
  for (const item of buttons) {
    const needed = item.width + (count ? gap : 0);
    if (used + needed > available) break;
    used += needed;
    count++;
  }
  return { visible: buttons.slice(0, count), overflow: buttons.slice(count) };
}

function layoutTraceToolbar() {
  const focused = document.activeElement;
  for (const button of playbackButtons) traceButtons.append(button);
  traceOverflow.hidden = false;
  const items = playbackButtons.map(button => ({ button, width: button.getBoundingClientRect().width }));
  const layout = traceLayout(items, traceToolbar.clientWidth, traceOverflow.getBoundingClientRect().width);
  for (const { button } of layout.visible) button.removeAttribute("role");
  for (const { button } of layout.overflow) { button.setAttribute("role", "menuitem"); traceMenu.append(button); }
  traceOverflow.hidden = !layout.overflow.length;
  if (traceOverflow.hidden) setTraceMenu(false);
  if (playbackButtons.includes(focused)) {
    (traceMenu.hidden && traceMenu.contains(focused) ? traceOverflow : focused).focus({ preventScroll: true });
  } else if (focused === traceOverflow && traceOverflow.hidden) {
    playbackButtons.find(button => !button.disabled)?.focus({ preventScroll: true });
  }
}

function setTraceMenu(open, focus = false) {
  traceMenu.hidden = !open;
  traceOverflow.setAttribute("aria-expanded", String(open));
  if (focus) (open ? traceMenu.querySelector("button:not(:disabled)") : traceOverflow)?.focus();
}

function traceMenuKeyboard(event) {
  if (event.key === "Escape") {
    event.preventDefault(); event.stopPropagation(); setTraceMenu(false, true); return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const buttons = [...traceMenu.querySelectorAll("button:not(:disabled)")];
  const current = buttons.indexOf(document.activeElement);
  const index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
    : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
  buttons[index]?.focus();
}

function bindTraceOverflow() {
  traceOverflow.addEventListener("click", () => setTraceMenu(traceMenu.hidden, true));
  traceOverflow.addEventListener("keydown", event => {
    if (event.key === "ArrowDown") { event.preventDefault(); setTraceMenu(true, true); }
    if (event.key === "Escape") { event.preventDefault(); setTraceMenu(false, true); }
  });
  traceMenu.addEventListener("keydown", traceMenuKeyboard);
  traceMenu.addEventListener("click", event => {
    if (event.target.closest("button:not(:disabled)")) setTraceMenu(false, true);
  });
  traceToolbar.addEventListener("focusout", event => {
    if (event.relatedTarget && !traceToolbar.contains(event.relatedTarget)) setTraceMenu(false);
  });
  document.addEventListener("pointerdown", event => {
    if (!traceToolbar.contains(event.target)) setTraceMenu(false);
  });
  new ResizeObserver(layoutTraceToolbar).observe(traceToolbar);
  document.fonts.ready.then(layoutTraceToolbar);
  layoutTraceToolbar();
}

function send(type, fields = {}) {
  if (state) vscode.postMessage({ type, version: state.version, ...fields });
}

function selectNode(node) {
  send(state?.trace && node.kind !== "external" ? "traceSeek" : "select", { usr: node.usr });
}

function element(name, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function nodeElement(node) {
  const status = ["stub", "implemented", "tested"].includes(node.status) ? node.status : "";
  const classes = ["node", status, node.kind === "external" ? "external" : "", node.change,
    node.root ? "root" : "", node.selected ? "selected" : ""].filter(Boolean).join(" ");
  const group = element("g", { class: classes, transform: `translate(${node.x} ${node.y})`,
    tabindex: 0, role: "button", "aria-label": node.tooltip, "aria-pressed": node.selected, "data-usr": node.usr });
  group.append(element("title", {}, node.tooltip), element("rect", { x: -100, y: -15, width: 200, height: 30, rx: 3 }));
  const label = node.label.length > 25 ? `…${node.label.slice(-24)}` : node.label;
  group.append(element("text", { "text-anchor": "middle", y: 4 }, label));
  if (node.change) group.append(element("text", { class: "badge", x: 96, y: -5 }, node.change === "added" ? "+" : "Δ"));
  group.addEventListener("click", () => { if (!moved) selectNode(node); });
  group.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    selectNode(node);
  });
  return group;
}

function edgePath(edge, a, b) {
  if (edge.source === edge.target) {
    return { path: `M ${a.x + 100} ${a.y - 8} C ${a.x + 136} ${a.y - 35}, ${a.x + 136} ${a.y + 35}, ${a.x + 100} ${a.y + 8}`,
      x: a.x + 128, y: a.y - 18 };
  }
  const half = a.x <= b.x ? 100 : -100;
  const x1 = a.x + half, x2 = b.x - half;
  if (a.x === b.x) {
    const x = a.x + 135;
    return { path: `M ${x1} ${a.y} C ${x} ${a.y}, ${x} ${b.y}, ${b.x + 100} ${b.y}`,
      x, y: (a.y + b.y) / 2 };
  }
  const middle = (x1 + x2) / 2;
  return { path: `M ${x1} ${a.y} C ${middle} ${a.y}, ${middle} ${b.y}, ${x2} ${b.y}`,
    x: middle, y: (a.y + b.y) / 2 - 5 };
}

function edgeElement(edge, nodes) {
  const curve = edgePath(edge, nodes.get(edge.source), nodes.get(edge.target));
  const classes = ["edge", edge.loop ? "loop" : "", edge.uncertain ? "uncertain" : "",
    edge.free ? "free" : "", edge.repeatCount ? "recorded" : ""].join(" ");
  const group = element("g", { class: classes, "data-source": edge.source, "data-target": edge.target });
  group.append(element("path", { d: curve.path }));
  const label = [edge.label, edge.uncertain ? "?" : "", edge.repeatCount ? `×${edge.repeatCount}` : ""].filter(Boolean).join(" · ");
  if (label) group.append(element("text", { x: curve.x, y: curve.y }, label));
  group.append(element("title", {}, [edge.source, "→", edge.target, edge.uncertain ? "(uncertain)" : ""].join(" ")));
  return group;
}

function drawGraph(graph) {
  const focused = document.activeElement?.getAttribute("data-usr");
  scene.replaceChildren();
  if (!graph) return;
  const nodes = new Map(graph.nodes.map(node => [node.usr, node]));
  for (const edge of graph.edges) scene.append(edgeElement(edge, nodes));
  for (const node of graph.nodes) {
    const group = nodeElement(node);
    scene.append(group);
    if (node.usr === focused) group.focus({ preventScroll: true });
  }
}

function updateControls(next) {
  if (drawnVersion !== next.version) {
    controls.root.replaceChildren(new Option(next.graph?.libraryMode ? "Library API (default)" : "Entry point (default)", ""));
    for (const choice of next.choices) controls.root.add(new Option(choice.label, choice.usr));
  }
  controls.root.value = next.root ?? "";
  controls.depth.value = String(next.depth);
  controls.callers.checked = next.callers;
  for (const control of Object.values(controls)) control.disabled = next.loading || !next.graph;
  const status = document.getElementById("status");
  status.textContent = next.message;
  status.title = next.message;
  updateTrace(next);
}

function updateTrace(next) {
  document.getElementById("traceLoad").disabled = next.loading || !next.graph;
  for (const [action, button] of Object.entries(traceControls)) {
    button.disabled = !next.trace?.availability[action];
  }
  const status = document.getElementById("traceStatus");
  status.textContent = next.proposal ? "Proposal source · added/changed outlines"
    : `Trace playback · ${next.trace?.status ?? "No trace loaded. Choose Load Trace."}`;
  const call = next.trace?.currentCall;
  status.title = status.textContent + (call ? ` · thread ${call.threadId} · depth ${call.depth}` : "");
}

function render(next) {
  if (next.type !== "render") return;
  traceToolbar.hidden = Boolean(next.proposal);
  updateControls(next);
  const trace = next.trace ? `${next.trace.traceId}:${next.trace.position}` : "";
  const redraw = next.version !== drawnVersion || trace !== drawnTrace;
  state = next;
  if (redraw) drawGraph(next.graph);
  for (const node of scene.querySelectorAll(".node")) {
    const selected = node.getAttribute("data-usr") === next.selected;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  }
  // Loading and loaded states share a version: draw the received graph once it exists.
  drawnVersion = next.graph ? next.version : undefined;
  drawnTrace = trace;
  globalThis.icodaGraphInteractions?.render(next, send);
  viewport = next.viewport;
  if (next.graph && !viewport) fit();
  else transform();
}

function transform() {
  if (viewport) scene.setAttribute("transform", `translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`);
}

function move(next) {
  viewport = { x: Math.max(-1e7, Math.min(1e7, next.x)), y: Math.max(-1e7, Math.min(1e7, next.y)), scale: next.scale };
  transform();
  send("viewport", { viewport });
}

function fit() {
  if (state?.graph && svg.clientWidth && svg.clientHeight) send("fit", { width: svg.clientWidth, height: svg.clientHeight });
}

function zoom(factor, x = svg.clientWidth / 2, y = svg.clientHeight / 2) {
  if (!viewport) return;
  const scale = Math.max(0.1, Math.min(4, viewport.scale * factor));
  const ratio = scale / viewport.scale;
  move({ scale, x: x - (x - viewport.x) * ratio, y: y - (y - viewport.y) * ratio });
}

function bindControls() {
  controls.root.addEventListener("change", () => send("root", { usr: controls.root.value || null }));
  controls.depth.addEventListener("change", () => send("depth", { depth: controls.depth.valueAsNumber }));
  controls.callers.addEventListener("change", () => send("callers", { callers: controls.callers.checked }));
  controls.zoomIn.addEventListener("click", () => zoom(1.2));
  controls.zoomOut.addEventListener("click", () => zoom(1 / 1.2));
  controls.fit.addEventListener("click", fit);
  document.getElementById("traceLoad").addEventListener("click", () => send("traceLoad"));
  for (const [action, button] of Object.entries(traceControls)) {
    button.addEventListener("click", () => send(action === "reset" ? "traceReset" : "traceStep",
      action === "reset" ? {} : { action }));
  }
}

function pointerDown(event) {
  if (event.button !== 0 || !viewport) return;
  moved = false;
  drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, viewport: { ...viewport } };
  if (!event.target.closest(".node")) svg.focus({ preventScroll: true });
}

function pointerMove(event) {
  if (!drag || drag.pointer !== event.pointerId) return;
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  if (!moved && Math.hypot(dx, dy) < 4) return;
  moved = true;
  svg.setPointerCapture(event.pointerId);
  svg.classList.add("dragging");
  move({ ...drag.viewport, x: drag.viewport.x + dx, y: drag.viewport.y + dy });
}

function pointerUp(event) {
  drag = undefined;
  svg.classList.remove("dragging");
  if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
}

function wheel(event) {
  event.preventDefault();
  if (!viewport) return;
  if (event.ctrlKey || event.metaKey) {
    const box = svg.getBoundingClientRect();
    zoom(Math.exp(-event.deltaY * 0.002), event.clientX - box.left, event.clientY - box.top);
  } else {
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? svg.clientHeight : 1;
    move({ ...viewport, x: viewport.x - event.deltaX * unit, y: viewport.y - event.deltaY * unit });
  }
}

function keyboard(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || !viewport) return;
  const offsets = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] };
  if (offsets[event.key]) {
    const [dx, dy] = offsets[event.key];
    move({ ...viewport, x: viewport.x + dx, y: viewport.y + dy });
  } else if (["+", "="].includes(event.key)) zoom(1.2);
  else if (event.key === "-") zoom(1 / 1.2);
  else if (event.key.toLowerCase() === "f") fit();
  else return;
  event.preventDefault();
}

bindControls();
bindTraceOverflow();
svg.addEventListener("pointerdown", pointerDown);
svg.addEventListener("pointermove", pointerMove);
svg.addEventListener("pointerup", pointerUp);
svg.addEventListener("pointercancel", pointerUp);
svg.addEventListener("lostpointercapture", pointerUp);
svg.addEventListener("wheel", wheel, { passive: false });
svg.addEventListener("keydown", keyboard);
window.addEventListener("message", event => render(event.data));
window.addEventListener("resize", () => { if (!viewport) fit(); });
vscode.postMessage({ type: "ready" });
