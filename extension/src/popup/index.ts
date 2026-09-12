import "./styles.css";
import { webExtension } from "../browser-api";
import { openGuiInNewTab, openGuiInSidePanel } from "../gui";
import {
  interfaceLanguage,
  localizeDocument,
  message,
  type MessageKey,
} from "../i18n";
import { initializeTheme, saveTheme, type UiTheme } from "../theme";

const darkLogoUrl = new URL(
  "../../../web/src/assets/elsewise-logo-dark.svg",
  import.meta.url,
).href;
const lightLogoUrl = new URL(
  "../../../web/src/assets/elsewise-logo-light.svg",
  import.meta.url,
).href;

interface PopupSource {
  tabId: number;
  platform: string;
  health: string;
  speaker: string;
  sourceEpochId?: string;
  lastEventAt?: string;
}

interface PopupStatus {
  daemon: "connected" | "reconnecting" | "not_paired" | "unavailable";
  pairing: "unpaired" | "pending" | "paired" | "denied" | "expired" | "error";
  pending: number;
  dropped: number;
  capacityPercent: number;
  bufferFull: boolean;
  session: Record<string, unknown> | null;
  sources: PopupSource[];
}

const element = <T extends HTMLElement>(id: string): T => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing popup element: ${id}`);
  return found as T;
};

const statusLabels: Partial<Record<string, MessageKey>> = {
  connected: "connected",
  reconnecting: "reconnecting",
  not_paired: "notPaired",
  unavailable: "unavailable",
  running: "running",
  stopping: "stopping",
  stopped: "stopped",
  none: "none",
  available: "captionsCapturingStatus",
  waiting: "captionsOnEmptyStatus",
  degraded: "degraded",
};

function localizedValue(value: string): string {
  const key = statusLabels[value];
  return key ? message(key) : value.replaceAll("_", " ");
}

function platformLabel(value: string): string {
  if (value === "google_meet") return "Google Meet";
  if (value === "microsoft_teams") return "Microsoft Teams";
  if (value === "zoom") return "Zoom";
  if (value === "synthetic") return message("syntheticHarness");
  return message("unsupportedPage");
}

let activeTab:
  Awaited<ReturnType<typeof webExtension.tabs.query>>[number] | null = null;
let currentStatus: PopupStatus | null = null;

function render(status: PopupStatus): void {
  currentStatus = status;
  const source = status.sources.find((item) => item.tabId === activeTab?.id);
  element("platform").textContent = platformLabel(
    source?.platform ?? "unsupported",
  );
  element("capture").textContent = localizedValue(source?.health ?? "none");
  element("captions").textContent = source?.sourceEpochId
    ? message("sourceActive")
    : message("sourceWaiting");
  element("speaker").textContent = localizedValue(source?.speaker ?? "unknown");
  element("buffer").textContent =
    `${status.pending} ${message("pending")} · ${status.dropped} ${message("dropped")}`;
  element("buffer").classList.toggle("warning", status.capacityPercent >= 80);
  element("buffer-warning").textContent = status.bufferFull
    ? message("bufferFull")
    : status.capacityPercent >= 80
      ? message("bufferNearlyFull")
      : "";
  element("session").textContent = String(
    status.session?.title ??
      localizedValue(String(status.session?.recording_status ?? "none")),
  );
  element("last-event").textContent = source?.lastEventAt
    ? new Date(source.lastEventAt).toLocaleTimeString(interfaceLanguage())
    : message("never");
  const badge = element("daemon-badge");
  badge.textContent = localizedValue(status.daemon);
  badge.className = `badge ${status.daemon.replace("_", "-")}`;
  const pair = element<HTMLButtonElement>("pair");
  const cancel = element<HTMLButtonElement>("cancel-pairing");
  pair.hidden = status.pairing === "paired" || status.pairing === "pending";
  cancel.hidden = status.pairing !== "pending";
  element("pairing-state").textContent = message(
    status.pairing === "paired"
      ? "pairingPaired"
      : status.pairing === "pending"
        ? "pairingPending"
        : "pairingRequired",
  );
  element("hint").textContent = source
    ? message("hintSourceManaged")
    : message("hintUnsupported");
}

element<HTMLImageElement>("brand-logo-dark").src = darkLogoUrl;
element<HTMLImageElement>("brand-logo-light").src = lightLogoUrl;
localizeDocument();

function renderTheme(theme: UiTheme): void {
  for (const candidate of ["dark", "light"] as const) {
    const button = element<HTMLButtonElement>(`theme-${candidate}`);
    button.classList.toggle("selected", candidate === theme);
    button.setAttribute("aria-pressed", String(candidate === theme));
  }
}

for (const theme of ["dark", "light"] as const) {
  element<HTMLButtonElement>(`theme-${theme}`).addEventListener("click", () => {
    renderTheme(theme);
    void saveTheme(theme);
  });
}
void initializeTheme(renderTheme);

async function refresh(): Promise<void> {
  const [tab] = await webExtension.tabs.query({
    active: true,
    currentWindow: true,
  });
  activeTab = tab ?? null;
  render(
    (await webExtension.runtime.sendMessage({
      type: "popup.status",
    })) as PopupStatus,
  );
}

element("pair").addEventListener("click", async () => {
  render(
    (await webExtension.runtime.sendMessage({
      type: "pairing.begin",
    })) as PopupStatus,
  );
});

element("cancel-pairing").addEventListener("click", async () => {
  render(
    (await webExtension.runtime.sendMessage({
      type: "pairing.cancel",
    })) as PopupStatus,
  );
});

element("dump").addEventListener("click", async () => {
  if (activeTab?.id === undefined) return;
  await webExtension.runtime.sendMessage({
    type: "diagnostics.dump",
    tabId: activeTab.id,
  });
  element("notice").textContent = message("diagnosticRequested");
});

element("copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(JSON.stringify(currentStatus, null, 2));
  element("notice").textContent = message("diagnosticsCopied");
});

element("open-side-panel").addEventListener("click", () => {
  if (activeTab?.id === undefined) return;
  void openGuiInSidePanel(activeTab.id).catch(() => {
    element("notice").textContent = message("sidePanelUnavailable");
  });
});

element("open-new-tab").addEventListener("click", () => {
  void openGuiInNewTab().catch(() => {
    element("notice").textContent = message("guiUnavailable");
  });
});

void refresh();
window.setInterval(() => void refresh(), 1000);
