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

function selectNode(node) {
  if (node.expandable) send("enter", { id: node.id });
  else if (node.kind !== "cluster") send("select", { id: node.id });
}

function element(name, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function memberLabel(member) {
  const name = member.kind === "field" ? `${member.name}: ${member.declaration}` : member.declaration || member.name;
  return `${member.visibility ? member.visibility + " " : ""}${name}${member.status ? ` [${member.status}]` : ""}`;
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

function nodeElement(node) {
  const tooltip = [node.label, node.file ? `${node.file}:${node.line}` : "", ...(node.members || []).map(memberLabel)].filter(Boolean).join("\n");
  const group = element("g", { class: `node ${node.kind}`, transform: `translate(${node.x} ${node.y})`,
    tabindex: 0, role: "button", "aria-label": tooltip, "data-id": node.id });
  group.append(element("title", {}, tooltip), element("rect", {
    x: -node.width / 2, y: -node.height / 2, width: node.width, height: node.height, rx: 3 }));
  if (node.expandable) {
    node.label.split("\n").forEach((line, i, lines) => group.append(element("text", {
      "text-anchor": "middle", y: (i - (lines.length - 1) / 2) * 18 + 4 }, line)));
  } else {
    group.append(element("text", { "text-anchor": "middle", y: -node.height / 2 + 20 }, shorten(node.label, 40)),
      element("text", { "text-anchor": "middle", y: -node.height / 2 + 38, class: "counts" }, `${node.kind} · ${node.members.length} members`));
    node.members.forEach((member, row) => group.append(memberElement(node, member, row)));
  }
  clickable(group, () => selectNode(node));
  return group;
}

function shorten(text, limit) { return text.length > limit ? text.slice(0, limit - 1) + "…" : text; }

function memberElement(node, member, row) {
  const top = -node.height / 2 + state.graph.headerHeight + row * state.graph.memberHeight;
  const label = memberLabel(member);
  const group = element("g", { class: "member", tabindex: 0, role: "button", "data-id": member.usr,
    "aria-label": `${label} · ${member.file}:${member.line}` });
  group.append(element("title", {}, `${label}\n${member.file}:${member.line}`),
    element("rect", { x: -node.width / 2, y: top, width: node.width, height: state.graph.memberHeight }),
    element("text", { x: -node.width / 2 + 8, y: top + state.graph.memberHeight / 2 + 4 }, shorten(label, 44)));
  clickable(group, () => send("select", { id: member.usr }));
  return group;
}

function edgePoint(node, towards) {
  const dx = towards.x - node.x, dy = towards.y - node.y;
  const factor = Math.min(dx ? node.width / 2 / Math.abs(dx) : Infinity,
    dy ? node.height / 2 / Math.abs(dy) : Infinity);
  return [node.x + dx * factor, node.y + dy * factor];
}

function edgeElement(edge, nodes) {
  const a = nodes.get(edge.source), b = nodes.get(edge.target);
  const group = element("g", { class: `edge ${edge.kind}`, "data-source": edge.source, "data-target": edge.target });
  const offset = { inheritance: -28, composition: 0, usage: 28 }[edge.kind];
  let path, x, y;
  if (a === b) {
    const right = a.x + a.width / 2, top = a.y - a.height / 4;
    x = right + 50 + offset; y = top;
    path = `M ${right} ${top - 18} C ${x + 50} ${top - 40} ${x + 50} ${top + 40} ${right} ${top + 18}`;
  } else {
    const [x1, y1] = edgePoint(a, b), [x2, y2] = edgePoint(b, a);
    const length = Math.hypot(x2 - x1, y2 - y1) || 1;
    const cx = (x1 + x2) / 2 - (y2 - y1) / length * offset * 2;
    const cy = (y1 + y2) / 2 + (x2 - x1) / length * offset * 2;
    path = `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
    x = (x1 + 2 * cx + x2) / 4; y = (y1 + 2 * cy + y2) / 4;
  }
  group.append(element("path", { d: path }), element("title", {}, `${a.label} → ${b.label}: ${edge.kind} ×${edge.count}`),
    element("text", { x, y: y - 5 }, `${edge.kind} ×${edge.count}`));
  return group;
}

function drawGraph(graph) {
  const focused = document.activeElement?.getAttribute("data-id");
  scene.replaceChildren();
  if (!graph) return;
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  for (const edge of graph.edges) scene.append(edgeElement(edge, nodes));
  for (const node of graph.nodes) {
    const group = nodeElement(node);
    scene.append(group);
    if (node.id === focused) group.focus({ preventScroll: true });
  }
}

function render(next) {
  if (next.type !== "render") return;
  state = next;
  if (next.version !== drawnVersion) drawGraph(next.graph);
  drawnVersion = next.graph ? next.version : undefined;
  for (const node of scene.querySelectorAll(".node, .member")) {
    const selected = node.getAttribute("data-id") === next.selected;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  }
  document.getElementById("back").disabled = next.loading || !next.graph?.clusterId;
  document.getElementById("breadcrumb").textContent = ["Overview", ...(next.graph?.clusterPath || []).map(p => p.label)].join(" / ");
  for (const id of ["fit", "zoomIn", "zoomOut"]) document.getElementById(id).disabled = next.loading || !next.graph;
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

document.getElementById("back").addEventListener("click", () => send("back"));
document.getElementById("fit").addEventListener("click", fit);
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
