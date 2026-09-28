import { graphInteractionControls } from "./graphInteractions";
/** Only nonce-protected local resources enter HTML; all project text arrives as data. */
export function mindMapHtml(nonce: string, cspSource: string, script: string, style: string, interactions = script.replace(/[^/]+$/, "graphInteractions.js")): string {
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; style-src ${escape(cspSource)}; script-src 'nonce-${escape(nonce)}';">
<link rel="stylesheet" href="${escape(style)}"><title>ICODA Mind Map</title></head>
<body>
<div id="toolbar" role="toolbar" aria-label="Mind Map controls">
<span id="summary">Mind Map</span>
<button id="openStep" disabled title="Open the selected node's introducing step">Open Step</button>
${graphInteractionControls()}
<button id="zoomOut" aria-label="Zoom out">−</button><button id="fit">Fit</button>
<button id="zoomIn" aria-label="Zoom in">+</button></div>
<svg id="graph" tabindex="0" role="group" aria-label="Mind Map. Tab to nodes or expansion buttons; Enter selects; arrows pan; plus and minus zoom; F fits.">
<g id="scene"></g></svg>
<p id="status" role="status" aria-live="polite">Loading Mind Map…</p>
<script nonce="${escape(nonce)}" src="${escape(interactions)}"></script>
<script type="module" nonce="${escape(nonce)}" src="${escape(script)}"></script>
</body></html>`;
}

function escape(value: string): string {
  return value.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]!);
}
