import { graphInteractionControls } from "./graphInteractions";
/** Only nonce-protected local resources enter HTML; graph labels arrive as data. */
export function classViewHtml(nonce: string, cspSource: string, script: string, style: string, interactions = script.replace(/[^/]+$/, "graphInteractions.js")): string {
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; style-src ${escape(cspSource)}; script-src 'nonce-${escape(nonce)}';">
<link rel="stylesheet" href="${escape(style)}"><title>ICODA Class View</title></head>
<body>
<div id="toolbar" role="toolbar" aria-label="Class View controls">
<button id="back" disabled>← Overview</button><span id="breadcrumb">Whole Project</span>
${graphInteractionControls()}
<button id="zoomOut" aria-label="Zoom out">−</button><button id="fit">Fit</button>
<button id="zoomIn" aria-label="Zoom in">+</button></div>
<svg id="graph" tabindex="0" role="group" aria-label="Class graph. Enter opens a group, class or member; arrows pan; plus and minus zoom; F fits.">
<defs><marker id="inheritance" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 1 1 L 11 6 L 1 11 z" /></marker>
<marker id="composition" viewBox="0 0 16 12" refX="1" refY="6" markerWidth="10" markerHeight="8" orient="auto"><path d="M 1 6 L 8 1 L 15 6 L 8 11 z" /></marker>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
<g id="scene"></g></svg>
<p id="status" role="status" aria-live="polite">Loading Class View…</p>
<script nonce="${escape(nonce)}" src="${escape(interactions)}"></script>
<script type="module" nonce="${escape(nonce)}" src="${escape(script)}"></script>
</body></html>`;
}

function escape(value: string): string {
  return value.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]!);
}
