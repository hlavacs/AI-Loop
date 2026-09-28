import * as vscode from "vscode";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join } from "node:path";
import { stat } from "node:fs/promises";
import type { IntegrationTestApi } from "../../extension";
import { callView, command, pause, report } from "./helpers";

const execute = promisify(execFile);

async function capture(file: string): Promise<void> {
  const gdk = "import gi,sys; gi.require_version('Gdk','3.0'); from gi.repository import Gdk; "
    + "w=Gdk.get_default_root_window(); p=Gdk.pixbuf_get_from_window(w,0,0,w.get_width(),w.get_height()); "
    + "p.savev(sys.argv[1],'png',[],[])";
  const candidates = process.platform === "darwin" ? [["screencapture", "-x", file]]
    : [["import", "-window", "root", file], ["gnome-screenshot", "-f", file], ["python3", "-c", gdk, file]];
  const failures: string[] = [];
  for (const [program, ...args] of candidates) {
    try {
      await execute(program!, args, { timeout: 10_000 });
      if ((await stat(file)).size < 1024) throw new Error("empty screenshot");
      return;
    } catch (error) { failures.push(`${program}: ${String(error)}`); }
  }
  throw new Error(`Native screenshot capture failed: ${failures.join("\n")}`);
}

export async function screenshots(api: IntegrationTestApi): Promise<void> {
  await command("workbench.action.toggleFullScreen");
  await command("workbench.action.closePanel");
  await command("workbench.action.closeSidebar");
  await command("workbench.action.closeAuxiliaryBar");
  await command("notifications.clearAll");
  for (const [theme, title] of [["dark", "Default Dark Modern"], ["light", "Default Light Modern"]]) {
    await vscode.workspace.getConfiguration("workbench").update("colorTheme", title, vscode.ConfigurationTarget.Global);
    for (const [width, size] of [["wide", 0.75], ["narrow", 0.28]] as const) {
      await command("vscode.setEditorLayout", { orientation: 0, groups: [{ size }, { size: 1 - size }] });
      const hooks = await callView(api);
      const version = hooks.snapshot().version;
      await hooks.dispatch({ type: "viewport", version, viewport: { scale: 1, x: 16, y: 100 } });
      await hooks.dispatch({ type: "filter", version, text: "" });
      await pause(1200); // Allow native theme/layout painting before the screen capture.
      const file = join(report, `call-view-${theme}-${width}.png`);
      await capture(file);
      console.log(`Screenshot: ${file}`);
    }
  }
}
