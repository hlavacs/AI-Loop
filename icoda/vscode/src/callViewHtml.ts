import { graphInteractionControls } from "./graphInteractions";
/** Only extension-owned resource URIs enter HTML; graph text arrives through postMessage. */
export function callViewHtml(nonce: string, cspSource: string, script: string, style: string, interactions = script.replace(/[^/]+$/, "graphInteractions.js")): string {
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; style-src ${escape(cspSource)}; script-src 'nonce-${escape(nonce)}';">
<link rel="stylesheet" href="${escape(style)}"><title>ICODA Call View</title></head>
<body>
${toolbar()}
<svg id="graph" tabindex="0" role="group" aria-label="Call graph. Tab to functions; Enter to open source. Arrow keys pan; plus and minus zoom; F fits.">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
<g id="scene"></g></svg>
<p id="status" role="status" aria-live="polite">Loading Call View…</p>
<script nonce="${escape(nonce)}" src="${escape(interactions)}"></script>
<script type="module" nonce="${escape(nonce)}" src="${escape(script)}"></script>
</body></html>`;
}

function toolbar(): string {
  return `<div id="toolbar" class="call-toolbar" role="toolbar" aria-label="Call View controls">
<div id="traceToolbar" role="group" aria-label="Trace playback">
<div id="traceButtons">
<button id="traceLoad">Load Trace</button>
<button id="tracePrevious" title="Previous Call (Ctrl+Alt+Left)" disabled>Previous Call</button>
<button id="traceOver" title="Step Over (Ctrl+Alt+Down)" disabled>Step Over</button>
<button id="traceInto" title="Step Into (Ctrl+Alt+Right)" disabled>Step Into</button>
<button id="traceOut" title="Step Out (Ctrl+Alt+Up)" disabled>Step Out</button>
<button id="traceReset" title="Reset (Ctrl+Alt+Home)" disabled>Reset</button>
</div>
<button id="traceOverflow" aria-label="More trace playback controls" aria-haspopup="menu" aria-controls="traceMenu" aria-expanded="false" hidden>…</button>
<div id="traceMenu" role="menu" aria-label="Trace playback controls" hidden></div>
</div>
<div id="graphControls">
<span id="traceStatus" role="status" aria-live="polite">Trace playback · No trace loaded. Choose Load Trace.</span>
<label>Root <select id="root" title="Choose a graph root; selection alone keeps the root"><option value="">Entry points</option></select></label>
<label>Depth <input id="depth" type="number" min="0" max="12" value="3" aria-label="Call depth"></label>
<label><input id="callers" type="checkbox"> Callers</label>
${graphInteractionControls()}
<button id="zoomOut" title="Zoom out (−)" aria-label="Zoom out">−</button>
<button id="fit" title="Fit graph (F)">Fit</button>
<button id="zoomIn" title="Zoom in (+)" aria-label="Zoom in">+</button>
</div>
</div>`;
}

function escape(value: string): string {
  return value.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]!);
}
