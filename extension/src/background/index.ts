import type {
  SourceStatus,
  UtteranceFinalize,
  UtteranceUpsert,
} from "../protocol/models";
import { PersistentEventBuffer } from "./event-buffer";
import { backgroundApi } from "./browser-api";
import { FrameElection } from "./frame-election";
import { BrowserStorageArea } from "./storage";
import { IngestTransport, type TransportState } from "./transport";

const extensionVersion = __EXTENSION_VERSION__;

interface PopupStatus extends TransportState {
  enabledTabId: number | null;
  platform: string;
  captions: string;
  speaker: string;
  lastEventAt: string | null;
}

const ports = new Map<
  number,
  Map<number, ReturnType<typeof backgroundApi.runtime.connect>>
>();
const frameElection = new FrameElection();
let enabledTabId: number | null = null;
let transport: IngestTransport | null = null;
let transportState: TransportState = {
  daemon: "unavailable",
  pending: 0,
  dropped: 0,
  pendingBytes: 0,
  capacityPercent: 0,
  bufferFull: false,
  session: null,
};
let captureState = {
  platform: "unsupported",
  captions: "unknown",
  speaker: "unknown",
};
let lastEventAt: string | null = null;
let clientSequence = 0;
let installationId = "";
let activeSourceId: string | null = null;
let activeDocumentId: string | null = null;
let adapterMessageQueue: Promise<void> = Promise.resolve();
const COORDINATOR_KEY = "coordinatorStateV1";
const sourceStatusTabs = new Map<
  string,
  { requestedTabId: number; previousTabId: number | null }
>();
let pendingPreviousTabId: number | null = null;

function messageRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function queueAdapterMessage(operation: () => Promise<void>): void {
  const result = adapterMessageQueue.then(operation, operation);
  adapterMessageQueue = result.catch((error: unknown) => {
    console.error("Failed to process an adapter message", error);
  });
}

function postToTab(tabId: number, message: Record<string, unknown>): void {
  for (const port of ports.get(tabId)?.values() ?? [])
    port.postMessage(message);
}

function postToCaptureFrame(
  tabId: number,
  message: Record<string, unknown>,
): void {
  const tabPorts = ports.get(tabId);
  if (!tabPorts) return;
  const elected = frameElection.frameFor(tabId);
  const port = elected === undefined ? tabPorts.get(0) : tabPorts.get(elected);
  (port ?? tabPorts.values().next().value)?.postMessage(message);
}

async function persistCoordinator(): Promise<void> {
  await backgroundApi.storage.session.set({
    [COORDINATOR_KEY]: {
      enabledTabId,
      clientSequence,
      captureState,
      lastEventAt,
      activeSourceId,
      activeDocumentId,
    },
  });
}

async function restoreCoordinator(): Promise<void> {
  const stored = await backgroundApi.storage.session.get(COORDINATOR_KEY);
  const state = stored[COORDINATOR_KEY] as
    | {
        enabledTabId?: number | null;
        clientSequence?: number;
        captureState?: typeof captureState;
        lastEventAt?: string | null;
        activeSourceId?: string | null;
        activeDocumentId?: string | null;
      }
    | undefined;
  enabledTabId = state?.enabledTabId ?? null;
  clientSequence = state?.clientSequence ?? 0;
  captureState = state?.captureState ?? captureState;
  lastEventAt = state?.lastEventAt ?? null;
  activeSourceId = state?.activeSourceId ?? null;
  activeDocumentId = state?.activeDocumentId ?? null;
}

function sourceId(tabId: number, documentId: string): string {
  return `${installationId}:${tabId}:${documentId}`.slice(0, 256);
}

async function ensureInstallationId(): Promise<string> {
  const stored = await backgroundApi.storage.local.get("installationId");
  if (typeof stored.installationId === "string") return stored.installationId;
  const generated = crypto.randomUUID();
  await backgroundApi.storage.local.set({ installationId: generated });
  return generated;
}

async function startTransport(): Promise<void> {
  transport?.stop();
  installationId = await ensureInstallationId();
  const stored = await backgroundApi.storage.local.get("pairingToken");
  const token =
    typeof stored.pairingToken === "string" ? stored.pairingToken : "";
  transport = new IngestTransport(
    new PersistentEventBuffer(
      new BrowserStorageArea(backgroundApi.storage.session),
    ),
    token,
    installationId,
    extensionVersion,
    undefined,
    undefined,
    (state) => {
      transportState = state;
    },
    (ack) => {
      const pending = sourceStatusTabs.get(ack.event_id);
      sourceStatusTabs.delete(ack.event_id);
      if (!pending) return;
      if (
        ack.result === "rejected" &&
        ack.reason === "source_switch_rejected"
      ) {
        postToTab(pending.requestedTabId, { type: "capture.disable" });
        enabledTabId = pending.previousTabId;
        if (enabledTabId !== null)
          postToTab(enabledTabId, { type: "capture.enable" });
      } else if (
        pending.previousTabId !== null &&
        pending.previousTabId !== pending.requestedTabId
      ) {
        postToTab(pending.previousTabId, { type: "capture.disable" });
        frameElection.clear(pending.previousTabId);
      }
      void persistCoordinator();
    },
  );
  transport.start();
}

function status(): PopupStatus {
  return {
    ...transportState,
    enabledTabId,
    platform: captureState.platform,
    captions: captureState.captions,
    speaker: captureState.speaker,
    lastEventAt,
  };
}

function platformFromUrl(rawUrl?: string): string {
  if (!rawUrl) return "unsupported";
  const url = new URL(rawUrl);
  if (url.hostname === "meet.google.com") return "google_meet";
  if (
    url.hostname === "teams.live.com" ||
    url.hostname === "teams.microsoft.com" ||
    url.hostname.endsWith(".teams.microsoft.com")
  ) {
    return "microsoft_teams";
  }
  if (url.hostname === "app.zoom.us") return "zoom";
  if (
    url.hostname === "127.0.0.1" &&
    url.searchParams.has("elsewise-synthetic")
  ) {
    return "synthetic";
  }
  return "unsupported";
}

const initialization = (async () => {
  await restoreCoordinator();
  await startTransport();
})();

backgroundApi.runtime.onConnect.addListener((port) => {
  if (port.name !== "elsewise-content" || port.sender?.tab?.id === undefined)
    return;
  const tabId = port.sender.tab.id;
  const frameId = port.sender.frameId ?? 0;
  const documentId =
    (port.sender as typeof port.sender & { documentId?: string }).documentId ??
    `frame-${frameId}`;
  const tabPorts =
    ports.get(tabId) ??
    new Map<number, ReturnType<typeof backgroundApi.runtime.connect>>();
  tabPorts.set(frameId, port);
  ports.set(tabId, tabPorts);
  port.onDisconnect.addListener(() => {
    if (ports.get(tabId)?.get(frameId) === port)
      ports.get(tabId)?.delete(frameId);
    if (ports.get(tabId)?.size === 0) ports.delete(tabId);
    frameElection.disconnected(tabId, frameId);
  });
  port.onMessage.addListener((rawMessage) => {
    const message = messageRecord(rawMessage);
    if (message.type === "adapter.status")
      queueAdapterMessage(() =>
        handleAdapterStatus(tabId, frameId, documentId, message),
      );
    if (message.type === "adapter.utterance")
      queueAdapterMessage(() =>
        handleUtterance(tabId, frameId, documentId, message),
      );
    if (message.type === "diagnostics.bundle")
      void downloadDiagnostic(message.bundle);
  });
  void initialization.then(() => {
    if (enabledTabId === tabId) port.postMessage({ type: "capture.enable" });
  });
});

async function handleAdapterStatus(
  tabId: number,
  frameId: number,
  documentId: string,
  message: Record<string, unknown>,
): Promise<void> {
  if (tabId !== enabledTabId || !transport) return;
  if (
    !frameElection.acceptStatus(
      tabId,
      frameId,
      String(message.captionsStatus ?? "unknown"),
      Number(message.confidence ?? 0),
    )
  )
    return;
  captureState = {
    platform: String(message.platform ?? "unsupported"),
    captions: String(message.captionsStatus ?? "unknown"),
    speaker: String(message.speakerDetection ?? "unknown"),
  };
  lastEventAt = new Date().toISOString();
  clientSequence += 1;
  activeDocumentId = documentId;
  activeSourceId = sourceId(tabId, documentId);
  await persistCoordinator();
  const event: SourceStatus = {
    type: "source.status",
    protocol_version: 1,
    event_id: crypto.randomUUID(),
    source_id: activeSourceId,
    tab_id: tabId,
    document_id: documentId,
    client_seq: clientSequence,
    platform: captureState.platform as SourceStatus["platform"],
    enabled: true,
    captions_status: captureState.captions as SourceStatus["captions_status"],
    speaker_detection:
      captureState.speaker as SourceStatus["speaker_detection"],
    meeting_key: String(message.meetingKey ?? `tab-${tabId}`),
    observed_at: lastEventAt,
  };
  sourceStatusTabs.set(event.event_id, {
    requestedTabId: tabId,
    previousTabId: pendingPreviousTabId,
  });
  pendingPreviousTabId = null;
  const accepted = await transport.enqueue(event);
  if (!accepted) {
    const pending = sourceStatusTabs.get(event.event_id);
    sourceStatusTabs.delete(event.event_id);
    postToTab(tabId, { type: "capture.disable" });
    enabledTabId = pending?.previousTabId ?? null;
    if (enabledTabId !== null)
      postToTab(enabledTabId, { type: "capture.enable" });
    await persistCoordinator();
  }
}

async function handleUtterance(
  tabId: number,
  frameId: number,
  documentId: string,
  message: Record<string, unknown>,
): Promise<void> {
  if (tabId !== enabledTabId || !transport) return;
  if (!frameElection.acceptUtterance(tabId, frameId)) return;
  clientSequence += 1;
  lastEventAt = new Date().toISOString();
  activeDocumentId = documentId;
  activeSourceId = sourceId(tabId, documentId);
  await persistCoordinator();
  const common = {
    protocol_version: 1 as const,
    event_id: crypto.randomUUID(),
    source_id: activeSourceId,
    client_seq: clientSequence,
    platform: captureState.platform as UtteranceUpsert["platform"],
    meeting_key: String(message.meetingKey ?? `tab-${tabId}`),
    utterance_id: String(message.utteranceId),
    revision: Number(message.revision),
    speaker: typeof message.speaker === "string" ? message.speaker : null,
    text: String(message.text),
    observed_at: String(message.observedAt ?? lastEventAt),
  };
  const event: UtteranceUpsert | UtteranceFinalize =
    message.eventType === "finalize"
      ? { ...common, type: "utterance.finalize" }
      : { ...common, type: "utterance.upsert" };
  await transport.enqueue(event);
}

async function downloadDiagnostic(bundle: unknown): Promise<void> {
  const encoded = encodeURIComponent(JSON.stringify(bundle, null, 2));
  await backgroundApi.downloads.download({
    url: `data:application/json;charset=utf-8,${encoded}`,
    filename: `elsewise-caption-diagnostic-${Date.now()}.json`,
    saveAs: true,
  });
}

async function disableCapture(
  tabId: number,
  { notifyContent = true }: { notifyContent?: boolean } = {},
): Promise<void> {
  if (notifyContent) postToTab(tabId, { type: "capture.disable" });
  frameElection.clear(tabId);
  if (enabledTabId !== tabId) return;
  if (transport) {
    clientSequence += 1;
    const observedAt = new Date().toISOString();
    await transport.enqueue({
      type: "source.status",
      protocol_version: 1,
      event_id: crypto.randomUUID(),
      source_id:
        activeSourceId ?? sourceId(tabId, activeDocumentId ?? "unknown"),
      tab_id: tabId,
      document_id: activeDocumentId ?? "unknown",
      client_seq: clientSequence,
      platform: captureState.platform as SourceStatus["platform"],
      enabled: false,
      captions_status: "off",
      observed_at: observedAt,
    });
  }
  for (const [eventId, pending] of sourceStatusTabs) {
    if (pending.requestedTabId === tabId) sourceStatusTabs.delete(eventId);
  }
  enabledTabId = null;
  activeSourceId = null;
  activeDocumentId = null;
  pendingPreviousTabId = null;
  captureState = { ...captureState, captions: "off", speaker: "unknown" };
  await persistCoordinator();
}

backgroundApi.tabs.onRemoved.addListener((tabId) => {
  if (tabId === enabledTabId)
    queueAdapterMessage(() => disableCapture(tabId, { notifyContent: false }));
  else frameElection.clear(tabId);
});

backgroundApi.runtime.onMessage.addListener(
  (rawMessage, _sender, sendResponse) => {
    const message = messageRecord(rawMessage);
    void (async () => {
      await initialization;
      if (message.type === "popup.status") sendResponse(status());
      if (message.type === "pairing.save") {
        await backgroundApi.storage.local.set({
          pairingToken: String(message.token),
        });
        await startTransport();
        sendResponse(status());
      }
      if (message.type === "capture.enable") {
        const tabId = Number(message.tabId);
        // The session cached from server.hello may be stale until the next
        // heartbeat. Let the server authoritatively accept or reject a source
        // switch; the event acknowledgement restores the previous tab when
        // recording is active.
        pendingPreviousTabId = enabledTabId;
        enabledTabId = tabId;
        captureState = {
          ...captureState,
          platform: platformFromUrl(message.url as string),
        };
        await persistCoordinator();
        postToTab(tabId, { type: "capture.enable" });
        sendResponse(status());
      }
      if (message.type === "capture.disable") {
        const tabId = Number(message.tabId);
        await disableCapture(tabId);
        sendResponse(status());
      }
      if (message.type === "diagnostics.dump") {
        postToCaptureFrame(Number(message.tabId), {
          type: "diagnostics.dump",
          redactText: true,
          redactNames: true,
        });
        sendResponse({ ok: true });
      }
    })();
    return true;
  },
);
