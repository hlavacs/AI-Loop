/* Presentation only: Python supplies the visible nodes, edge counts and layout. */
"use strict";
const vscode = acquireVsCodeApi();
const svg = document.getElementById("graph");
const scene = document.getElementById("scene");
const clusterMenu = document.getElementById("clusterMenu");
let menuCluster;
let menuAnchor;
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
  else if (node.kind === "file") send("select", { id: node.id });
}

function closeClusterMenu(focus = false) {
  clusterMenu.hidden = true;
  if (focus) menuAnchor?.focus({ preventScroll: true });
  menuCluster = undefined;
}

function openClusterMenu(event, cluster, anchor) {
  if (!cluster || (cluster.kind !== "file" && !cluster.id.startsWith("cluster:")) || state?.loading) return;
  event.preventDefault();
  event.stopPropagation();
  menuCluster = cluster;
  menuAnchor = anchor;
  const file = cluster.kind === "file";
  document.getElementById("clusterPin").hidden = file;
  document.getElementById("clusterRename").hidden = file;
  document.getElementById("fileAssign").hidden = !file;
  clusterMenu.setAttribute("aria-label", file ? "File actions" : "Cluster actions");
  document.getElementById("clusterPin").textContent = cluster.pinned ? "Unpin Cluster" : "Pin Cluster";
  clusterMenu.hidden = false;
  const box = anchor.getBoundingClientRect();
  clusterMenu.style.left = `${Math.max(0, Math.min(event.clientX ?? box.left, window.innerWidth - clusterMenu.offsetWidth))}px`;
  clusterMenu.style.top = `${Math.max(0, Math.min(event.clientY ?? box.bottom, window.innerHeight - clusterMenu.offsetHeight))}px`;
  document.getElementById(file ? "fileAssign" : "clusterPin").focus();
}

function element(name, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function nodeElement(node) {
  const tooltip = [node.file || node.label, node.pinned ? "Pinned" : "", node.renamed ? "Renamed" : ""].filter(Boolean).join(" · ");
  const group = element("g", { class: `node ${node.kind}`, transform: `translate(${node.x} ${node.y})`,
    tabindex: 0, role: "button", "aria-label": tooltip, "data-id": node.id });
  group.append(element("title", {}, tooltip), element("rect", {
    x: -node.width / 2, y: -node.height / 2, width: node.width, height: node.height, rx: 3 }));
  const lines = node.label.split("\n");
  lines.forEach((line, i) => group.append(element("text", {
    "text-anchor": "middle", y: (i - (lines.length - 1) / 2) * 18 + 4 }, line)));
  group.addEventListener("click", () => { if (!moved) selectNode(node); });
  if (node.kind === "cluster" || node.kind === "file") group.addEventListener("contextmenu", event => openClusterMenu(event, node, group));
  group.addEventListener("keydown", event => {
    if ((node.kind === "cluster" || node.kind === "file") && (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10"))) {
      openClusterMenu(event, node, group);
      return;
    }
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    selectNode(node);
  });
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
  const [x1, y1] = edgePoint(a, b), [x2, y2] = edgePoint(b, a);
  const group = element("g", { class: "edge", "data-source": edge.source, "data-target": edge.target });
  group.append(element("path", { d: `M ${x1} ${y1} L ${x2} ${y2}` }),
    element("title", {}, `${edge.source} → ${edge.target}: ${edge.label}`),
    element("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 5 }, `×${edge.count}`));
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
  if (next.loading || next.version !== drawnVersion) closeClusterMenu();
  if (next.version !== drawnVersion) drawGraph(next.graph);
  drawnVersion = next.graph ? next.version : undefined;
  for (const node of scene.querySelectorAll(".node")) {
    const selected = node.getAttribute("data-id") === next.selected;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  }
  document.getElementById("back").disabled = next.loading || !next.graph?.clusterId;
  document.getElementById("breadcrumb").textContent = ["Overview", ...(next.graph?.clusterPath || []).map(p => p.label)].join(" / ");
  document.getElementById("breadcrumb").disabled = next.loading || !next.graph?.clusterId?.startsWith("cluster:");
  for (const id of ["fit", "zoomIn", "zoomOut", "reveal"]) document.getElementById(id).disabled = next.loading || !next.graph;
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
for (const type of ["click", "contextmenu"]) document.getElementById("breadcrumb").addEventListener(type, event =>
  openClusterMenu(event, state?.graph?.clusterPath.at(-1), document.getElementById("breadcrumb")));
document.getElementById("clusterPin").addEventListener("click", () => {
  if (menuCluster) send(menuCluster.pinned ? "unpin" : "pin", { id: menuCluster.id });
  closeClusterMenu(true);
});
document.getElementById("clusterRename").addEventListener("click", () => {
  if (menuCluster) send("rename", { id: menuCluster.id });
  closeClusterMenu(true);
});
document.getElementById("fileAssign").addEventListener("click", () => {
  if (menuCluster?.kind === "file") send("assign", { id: menuCluster.id });
  closeClusterMenu(true);
});
clusterMenu.addEventListener("keydown", event => {
  if (event.key === "Escape") { event.preventDefault(); closeClusterMenu(true); }
  if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    if (menuCluster?.kind === "file") { document.getElementById("fileAssign").focus(); return; }
    const pin = document.getElementById("clusterPin"), rename = document.getElementById("clusterRename");
    (event.key === "Home" ? pin : event.key === "End" ? rename : document.activeElement === pin ? rename : pin).focus();
  }
});
document.addEventListener("pointerdown", event => { if (!clusterMenu.contains(event.target)) closeClusterMenu(); });
document.addEventListener("focusin", event => { if (!clusterMenu.contains(event.target)) closeClusterMenu(); });
document.getElementById("reveal").addEventListener("click", () => send("reveal"));
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
