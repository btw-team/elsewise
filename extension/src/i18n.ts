import { webExtension } from "./browser-api";

const englishFallback = {
  appName: "Elsewise",
  theme: "Theme",
  darkTheme: "Dark",
  lightTheme: "Light",
  unsupportedPage: "Unsupported page",
  syntheticHarness: "Synthetic harness",
  sourceLabel: "Source",
  captionsLabel: "Captions",
  speakerLabel: "Speaker",
  bufferLabel: "Buffer",
  sessionLabel: "Session",
  lastEventLabel: "Last event",
  enabled: "Enabled",
  disabled: "Disabled",
  notDetected: "Not detected",
  unknown: "Unknown",
  none: "None",
  never: "Never",
  pending: "pending",
  dropped: "dropped",
  bufferNearlyFull: "The caption buffer is at least 80% full.",
  bufferFull: "The caption buffer is full; new events are being dropped.",
  connected: "connected",
  disconnected: "disconnected",
  reconnecting: "reconnecting",
  notPaired: "not paired",
  unavailable: "unavailable",
  idle: "idle",
  running: "running",
  stopping: "stopping",
  stopped: "stopped",
  degraded: "degraded",
  captionsOffStatus: "Off",
  captionsOnEmptyStatus: "Enabled, no speech",
  captionsCapturingStatus: "Capturing",
  speakerAvailable: "Available",
  sourceActive: "Active",
  sourceWaiting: "Waiting for Session selection",
  hintSourceManaged:
    "Elsewise starts this source automatically for the active Session.",
  hintUnsupported: "Open Google Meet, Microsoft Teams, or Zoom to begin.",
  openSidePanel: "Open side panel",
  openNewTab: "Open in new tab",
  pair: "Pair",
  cancel: "Cancel",
  pairingRequired: "Pairing required",
  pairingPending: "Waiting for approval in Elsewise…",
  pairingPaired: "Paired with Elsewise",
  debug: "Debug",
  dumpCaptionDom: "Dump caption DOM",
  copyDiagnostics: "Copy diagnostics",
  diagnosticRequested: "A redacted diagnostic download was requested.",
  diagnosticsCopied: "Safe status summary copied.",
  currentTabUnavailable: "Unable to identify the current tab.",
  sidePanelUnavailable: "Unable to open the side panel.",
  guiUnavailable: "Unable to open Elsewise.",
  connectingServer: "Connecting to Elsewise…",
  startServer: "Start the Elsewise server",
  retry: "Retry",
} as const;

export type MessageKey = keyof typeof englishFallback;
type I18nApi = Pick<typeof webExtension.i18n, "getMessage" | "getUILanguage">;

export function message(
  key: MessageKey,
  i18n: I18nApi = webExtension.i18n,
): string {
  return i18n.getMessage(key) || englishFallback[key];
}

export function interfaceLanguage(i18n: I18nApi = webExtension.i18n): string {
  const raw = i18n.getUILanguage().replace("_", "-").toLowerCase();
  if (raw === "pt-br") return "pt-BR";
  const language = raw.split("-")[0];
  return language === "ru" ||
    language === "fr" ||
    language === "es" ||
    language === "de"
    ? language
    : "en";
}

export function localizeDocument(
  root: ParentNode = document,
  i18n: I18nApi = webExtension.i18n,
): void {
  document.documentElement.lang = interfaceLanguage(i18n);
  for (const node of root.querySelectorAll<HTMLElement>("[data-i18n]")) {
    const key = node.dataset.i18n as MessageKey | undefined;
    if (key) node.textContent = message(key, i18n);
  }
  for (const node of root.querySelectorAll<HTMLElement>(
    "[data-i18n-aria-label]",
  )) {
    const key = node.dataset.i18nAriaLabel as MessageKey | undefined;
    if (key) node.setAttribute("aria-label", message(key, i18n));
  }
}
