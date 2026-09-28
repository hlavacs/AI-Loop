/* Presentation only: Python supplies the visible nodes, edge counts and layout. */
"use strict";
const vscode = acquireVsCodeApi();
const svg = document.getElementById("graph");
const scene = document.getElementById("scene");
let state;
let viewport;
let drawnVersion;
let drag;
let moved = false;

function send(type, fields = {}) {
  if (state) vscode.postMessage({ type, version: state.version, ...fields });
}

function element(name, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function clickable(group, action) {
  group.addEventListener("click", event => { event.stopPropagation(); if (!moved) action(); });
  group.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    action();
  });
}

let focused;

function requirementLabel(requirement) {
  const status = requirement.uncovered === null ? "not in specification"
    : requirement.uncovered ? "no tagged entities" : "tagged in code";
  return `${requirement.id}: ${requirement.title || status} [${status}]`;
}

function nodeTooltip(node) {
  return [node.qualifiedName, `${node.kind} · ${node.status}`, ...node.requirements.map(requirementLabel),
    node.useCaseIds.length ? `Use cases: ${node.useCaseIds.join(", ")}` : "",
    node.step ? `Step #${node.step.number}: ${node.step.title}` : "Introducing step unknown",
    node.file ? `${node.file}:${node.line}` : ""].filter(Boolean).join("\n");
}

function nodeElement(node) {
  const tooltip = nodeTooltip(node);
  const group = element("g", { class: `node ${node.kind} ${node.status}`, transform: `translate(${node.x} ${node.y})`,
    tabindex: 0, role: "button", "aria-label": tooltip, "data-id": node.id, "data-focus": node.id });
  group.append(element("title", {}, tooltip), element("rect", {
    x: -node.width / 2, y: -node.height / 2, width: node.width, height: node.height, rx: 3 }));
  const x = -node.width / 2 + 30;
  const detail = [node.status, node.requirementIds.join(", "), node.step ? `step #${node.step.number}` : ""].filter(Boolean).join(" · ");
  group.append(element("text", { x, y: -2 }, shorten(`${node.kind} · ${node.label}`, 31)),
    element("text", { x, y: 12, class: "detail" }, shorten(detail, 38)));
  clickable(group, () => send("select", { nodeId: node.id }));
  if (node.expandable) group.append(expandElement(node));
  return group;
}

function expandElement(node) {
  const label = `${node.expanded ? "Collapse" : "Expand"} ${node.label}`;
  const group = element("g", { class: "expand", tabindex: 0, role: "button", "data-focus": `${node.id}:expand`,
    "aria-label": label, "aria-expanded": node.expanded });
  group.append(element("title", {}, label), element("rect", {
    x: -node.width / 2 + 3, y: -14, width: 22, height: 28, rx: 2 }),
    element("text", { x: -node.width / 2 + 14, y: 5, "text-anchor": "middle" }, node.expanded ? "−" : "+"));
  clickable(group, () => send("setExpanded", { nodeId: node.id, expanded: !node.expanded }));
  return group;
}

function shorten(text, limit) { return text.length > limit ? text.slice(0, limit - 1) + "…" : text; }

function drawGraph(graph) {
  focused = document.activeElement?.getAttribute("data-focus") || focused;
  scene.replaceChildren();
  if (!graph) return;
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  for (const edge of graph.edges) {
    const a = nodes.get(edge.source), b = nodes.get(edge.target);
    const group = element("g", { class: "edge", "data-source": edge.source, "data-target": edge.target });
    group.append(element("path", { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}` }));
    scene.append(group);
  }
  for (const node of graph.nodes) scene.append(nodeElement(node));
  for (const item of scene.querySelectorAll("[data-focus]")) {
    if (item.getAttribute("data-focus") === focused) item.focus({ preventScroll: true });
  }
}

function render(next) {
  if (next.type !== "render") return;
  state = next;
  if (next.version !== drawnVersion) drawGraph(next.graph);
  drawnVersion = next.graph ? next.version : undefined;
  for (const node of scene.querySelectorAll(".node")) {
    const selected = node.getAttribute("data-id") === next.selected;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  }
  document.getElementById("summary").textContent = next.graph
    ? `Mind Map · ${next.graph.nodes.length}/${next.graph.totalNodes} nodes` : "Mind Map";
  svg.setAttribute("aria-busy", String(next.loading));
  for (const id of ["fit", "zoomIn", "zoomOut"]) document.getElementById(id).disabled = next.loading || !next.graph;
  const selected = next.graph?.nodes.find(node => node.id === next.selected);
  document.getElementById("openStep").disabled = next.loading || !selected?.step;
  document.getElementById("status").textContent = next.message;
  document.getElementById("status").title = next.message;
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

document.getElementById("fit").addEventListener("click", fit);
document.getElementById("openStep").addEventListener("click", () => send("openStep", { nodeId: state.selected }));
document.getElementById("zoomIn").addEventListener("click", () => zoom(1.2));
document.getElementById("zoomOut").addEventListener("click", () => zoom(1 / 1.2));
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
