/* Shared presentation only. Matching and neighborhood traversal arrive from Python. */
"use strict";
(() => {
  const query = document.getElementById("graphQuery");
  const depth = document.getElementById("graphNeighborhood");
  const clear = document.getElementById("graphClear");
  const options = document.getElementById("graphOptions");
  const feedback = document.getElementById("graphFeedback");
  const scene = document.getElementById("scene");
  let state, send, timer;
  const submit = () => {
    if (state?.graph && !state.loading) send("graphOptions", { text: query.value, depth: Number(depth.value) });
  };
  query.addEventListener("input", () => {
    clearTimeout(timer);
    const version = state?.version;
    timer = setTimeout(() => { if (state?.version === version) submit(); }, 150);
  });
  depth.addEventListener("change", submit);
  clear.addEventListener("click", () => { clearTimeout(timer); query.value = ""; depth.value = "0"; submit(); });
  options.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      options.open = false;
      options.querySelector("summary").focus();
      event.preventDefault(); event.stopPropagation();
    }
  });
  globalThis.icodaGraphInteractions = {
    render(next, dispatch) {
      state = next; send = dispatch;
      const interaction = next.interactions;
      if (!interaction) return;
      if (document.activeElement !== query) query.value = interaction.text;
      if (document.activeElement !== depth) depth.value = String(interaction.depth);
      for (const control of [query, depth, clear]) control.disabled = next.loading || !next.graph;
      const decisions = interaction.decisions;
      const nodes = new Map((next.graph?.nodes || []).map(node => [node.id || node.usr, node]));
      const roots = new Set(next.graph?.roots || []);
      const flags = new Map();
      for (const item of scene.querySelectorAll(".node, .member")) {
        const id = item.getAttribute("data-id") || item.getAttribute("data-usr");
        const node = nodes.get(id);
        const selected = id === next.selected || node?.members?.some(member => member.usr === next.selected);
        // Nonmatching groups are filtered too; matching contents keep gateways reachable.
        const keep = selected || roots.has(id);
        const hidden = Boolean(decisions[id]?.hidden && !keep);
        const dimmed = Boolean(decisions[id]?.dimmed && !selected);
        item.classList.toggle("graph-filtered", hidden);
        item.classList.toggle("graph-dimmed", dimmed);
        item.setAttribute("aria-hidden", String(hidden));
        flags.set(id, { hidden, dimmed });
        if (hidden && item.contains(document.activeElement)) query.focus();
      }
      for (const edge of scene.querySelectorAll(".edge")) {
        const a = flags.get(edge.getAttribute("data-source")), b = flags.get(edge.getAttribute("data-target"));
        edge.classList.toggle("graph-filtered", Boolean(a?.hidden || b?.hidden));
        edge.classList.toggle("graph-dimmed", Boolean(a?.dimmed || b?.dimmed));
      }
      const hidden = [...flags.values()].filter(item => item.hidden).length;
      feedback.textContent = interaction.error || (interaction.pending ? "Updating…" : `${hidden} hidden · matching groups, roots and selection stay visible`);
    },
  };
})();
