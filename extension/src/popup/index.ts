import "./styles.css";
import { webExtension } from "../browser-api";
import { openGuiInNewTab, openGuiInSidePanel } from "../gui";
import {
  interfaceLanguage,
  localizeDocument,
  message,
  type MessageKey,
} from "../i18n";

interface PopupStatus {
  daemon: "connected" | "reconnecting" | "not_paired" | "unavailable";
  pending: number;
  dropped: number;
  pendingBytes: number;
  capacityPercent: number;
  bufferFull: boolean;
  session: Record<string, unknown> | null;
  enabledTabId: number | null;
  platform: string;
  captions: string;
  speaker: string;
  lastEventAt: string | null;
}

const element = <T extends HTMLElement>(id: string): T => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing popup element: ${id}`);
  return found as T;
};

const platformLabels: Partial<Record<string, MessageKey>> = {
  synthetic: "syntheticHarness",
  unsupported: "unsupportedPage",
};

const statusLabels: Partial<Record<string, MessageKey>> = {
  connected: "connected",
  reconnecting: "disconnected",
  not_paired: "notPaired",
  unavailable: "unavailable",
  idle: "idle",
  running: "running",
  stopped: "stopped",
  none: "none",
};

const captionLabels: Partial<Record<string, MessageKey>> = {
  unknown: "notDetected",
  off: "captionsOffStatus",
  on_empty: "captionsOnEmptyStatus",
  capturing: "captionsCapturingStatus",
};

const speakerLabels: Partial<Record<string, MessageKey>> = {
  unknown: "unknown",
  available: "speakerAvailable",
  unavailable: "unavailable",
};

function localizedValue(
  value: string,
  labels: Partial<Record<string, MessageKey>>,
): string {
  const key = labels[value];
  return key ? message(key) : value.replaceAll("_", " ");
}

function platformLabel(value: string): string {
  if (value === "google_meet") return "Google Meet";
  if (value === "microsoft_teams") return "Microsoft Teams";
  if (value === "zoom") return "Zoom";
  const key = platformLabels[value];
  return key ? message(key) : value;
}

let activeTab:
  Awaited<ReturnType<typeof webExtension.tabs.query>>[number] | null = null;
let currentStatus: PopupStatus | null = null;

function render(status: PopupStatus): void {
  currentStatus = status;
  element("platform").textContent = platformLabel(status.platform);
  element("capture").textContent =
    status.enabledTabId === activeTab?.id
      ? message("enabled")
      : message("disabled");
  element("captions").textContent = localizedValue(
    status.captions,
    captionLabels,
  );
  element("speaker").textContent = localizedValue(
    status.speaker,
    speakerLabels,
  );
  element("buffer").textContent =
    `${status.pending} ${message("pending")} · ${status.dropped} ${message("dropped")}`;
  const buffer = element("buffer");
  buffer.classList.toggle("warning", status.capacityPercent >= 80);
  element("buffer-warning").textContent = status.bufferFull
    ? message("bufferFull")
    : status.capacityPercent >= 80
      ? message("bufferNearlyFull")
      : "";
  element("session").textContent = String(
    status.session?.title ??
      localizedValue(
        String(status.session?.recording_status ?? "none"),
        statusLabels,
      ),
  );
  element("last-event").textContent = status.lastEventAt
    ? new Date(status.lastEventAt).toLocaleTimeString(interfaceLanguage())
    : message("never");
  const badge = element("daemon-badge");
  badge.textContent = localizedValue(status.daemon, statusLabels);
  badge.classList.toggle("connected", status.daemon === "connected");
  const toggle = element<HTMLButtonElement>("toggle");
  const supported = status.platform !== "unsupported";
  toggle.disabled = !supported;
  toggle.textContent =
    status.enabledTabId === activeTab?.id
      ? message("disableCapture")
      : message("enableCapture");
  element("hint").textContent =
    status.captions === "off"
      ? message("hintCaptionsOff")
      : status.captions === "on_empty"
        ? message("hintCaptionsEmpty")
        : supported
          ? message("hintCapture")
          : message("hintUnsupported");
}

localizeDocument();

async function refresh(): Promise<void> {
  const [tab] = await webExtension.tabs.query({
    active: true,
    currentWindow: true,
  });
  activeTab = tab ?? null;
  const status = (await webExtension.runtime.sendMessage({
    type: "popup.status",
  })) as PopupStatus;
  if (activeTab?.url) {
    const hostname = new URL(activeTab.url).hostname;
    if (hostname === "meet.google.com") status.platform = "google_meet";
    else if (
      hostname === "teams.live.com" ||
      hostname.includes("teams.microsoft.com")
    ) {
      status.platform = "microsoft_teams";
    } else if (hostname === "app.zoom.us") {
      status.platform = "zoom";
    } else if (hostname === "127.0.0.1") status.platform = "synthetic";
    else status.platform = "unsupported";
  }
  render(status);
}

element("toggle").addEventListener("click", async () => {
  if (activeTab?.id === undefined || !currentStatus) return;
  const enabled = currentStatus.enabledTabId === activeTab.id;
  const response = (await webExtension.runtime.sendMessage({
    type: enabled ? "capture.disable" : "capture.enable",
    tabId: activeTab.id,
    url: activeTab.url,
  })) as Record<string, unknown> | undefined;
  if (response?.error)
    element("notice").textContent = message("sourceSwitchRejected");
  else render(response as unknown as PopupStatus);
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
  if (activeTab?.id === undefined) {
    element("notice").textContent = message("currentTabUnavailable");
    return;
  }
  void openGuiInSidePanel(activeTab.id).catch(() => {
    element("notice").textContent = message("sidePanelUnavailable");
  });
});

element("open-new-tab").addEventListener("click", () => {
  void openGuiInNewTab().catch(() => {
    element("notice").textContent = message("guiUnavailable");
  });
});

element<HTMLFormElement>("pairing").addEventListener(
  "submit",
  async (event) => {
    event.preventDefault();
    const token = element<HTMLInputElement>("token").value.trim();
    if (!token) return;
    const status = (await webExtension.runtime.sendMessage({
      type: "pairing.save",
      token,
    })) as PopupStatus;
    element<HTMLInputElement>("token").value = "";
    element("notice").textContent = message("pairingSaved");
    render(status);
  },
);

void refresh();
