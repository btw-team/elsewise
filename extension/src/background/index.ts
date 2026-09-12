import type {
  CaptionFinalize,
  CaptionUpsert,
  SourceCommand,
  SourceCommandAck,
  SourceDiscovered,
  SourceHealth,
} from "../protocol/models";
import { PersistentEventBuffer } from "./event-buffer";
import { backgroundApi } from "./browser-api";
import { FrameElection } from "./frame-election";
import { BrowserStorageArea } from "./storage";
import { IngestTransport, type TransportState } from "./transport";

const extensionVersion = __EXTENSION_VERSION__;
const COORDINATOR_KEY = "sourceCoordinatorV2";

interface SourceRuntime {
  tabId: number;
  tabInstanceId: string;
  producerEpochId: string;
  platform: SourceDiscovered["platform"];
  activityKey?: string;
  health: SourceDiscovered["health_status"];
  speaker: string;
  sourceId?: string;
  sourceEpochId?: string;
  sessionId?: string;
  lastEventAt?: string;
}

interface PopupStatus extends TransportState {
  pairing: "unpaired" | "pending" | "paired" | "denied" | "expired" | "error";
  sources: SourceRuntime[];
}

const ports = new Map<
  number,
  Map<number, ReturnType<typeof backgroundApi.runtime.connect>>
>();
const frameElection = new FrameElection();
const sources = new Map<number, SourceRuntime>();
const discoveryRequests = new Map<string, number>();
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
let pairingState: PopupStatus["pairing"] = "unpaired";
let pairingSocket: WebSocket | null = null;
let clientSequence = 0;
let installationId = "";
let adapterMessageQueue: Promise<void> = Promise.resolve();

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

function postToCaptureFrame(
  tabId: number,
  message: Record<string, unknown>,
): boolean {
  const tabPorts = ports.get(tabId);
  if (!tabPorts) return false;
  const elected = frameElection.frameFor(tabId);
  const port = elected === undefined ? tabPorts.get(0) : tabPorts.get(elected);
  const target = port ?? tabPorts.values().next().value;
  if (!target) return false;
  target.postMessage(message);
  return true;
}

async function persistCoordinator(): Promise<void> {
  await backgroundApi.storage.session.set({
    [COORDINATOR_KEY]: {
      clientSequence,
      sources: [...sources.values()],
    },
  });
}

async function restoreCoordinator(): Promise<void> {
  const stored = await backgroundApi.storage.session.get(COORDINATOR_KEY);
  const state = stored[COORDINATOR_KEY] as
    { clientSequence?: number; sources?: SourceRuntime[] } | undefined;
  clientSequence = state?.clientSequence ?? 0;
  for (const source of state?.sources ?? []) sources.set(source.tabId, source);
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
  const stored = await backgroundApi.storage.local.get("clientCredential");
  const credential =
    typeof stored.clientCredential === "string" ? stored.clientCredential : "";
  pairingState = credential ? "paired" : "unpaired";
  transport = new IngestTransport(
    new PersistentEventBuffer(
      new BrowserStorageArea(backgroundApi.storage.session),
    ),
    credential,
    installationId,
    extensionVersion,
    undefined,
    undefined,
    (state) => {
      transportState = state;
      if (state.daemon === "not_paired" && pairingState === "paired") {
        pairingState = "unpaired";
        void backgroundApi.storage.local.remove("clientCredential");
      }
    },
    (ack) => {
      const tabId = discoveryRequests.get(ack.event_id);
      if (tabId === undefined) return;
      discoveryRequests.delete(ack.event_id);
      const source = sources.get(tabId);
      if (!source) return;
      if (typeof ack.details?.source_id === "string") {
        source.sourceId = ack.details.source_id;
      }
      if ("source_epoch_id" in (ack.details ?? {})) {
        if (typeof ack.details?.source_epoch_id === "string") {
          source.sourceEpochId = ack.details.source_epoch_id;
        } else {
          source.sourceEpochId = undefined;
          source.sessionId = undefined;
        }
      }
      void persistCoordinator();
    },
    (command) => handleSourceCommand(command),
    undefined,
    async () => {
      for (const source of sources.values()) await announceSource(source);
    },
  );
  transport.start();
}

function status(): PopupStatus {
  return {
    ...transportState,
    pairing: pairingState,
    sources: [...sources.values()],
  };
}

async function beginPairing(): Promise<void> {
  pairingSocket?.close();
  pairingState = "pending";
  installationId = await ensureInstallationId();
  const nonce = `${crypto.randomUUID()}${crypto.randomUUID()}`;
  const socket = new WebSocket("ws://127.0.0.1:38473/ws/pairing");
  pairingSocket = socket;
  socket.onopen = () => {
    socket.send(
      JSON.stringify({
        type: "pairing.request",
        protocol_version: 2,
        nonce,
        installation_id: installationId,
        browser_family: navigator.userAgent.includes("Firefox")
          ? "firefox"
          : "chrome",
        display_name: navigator.userAgent.includes("Firefox")
          ? "Firefox extension"
          : "Chrome extension",
        extension_version: extensionVersion,
      }),
    );
  };
  socket.onmessage = (event) => {
    const message = messageRecord(JSON.parse(String(event.data)));
    if (
      message.type === "pairing.approved" &&
      typeof message.credential === "string"
    ) {
      void backgroundApi.storage.local
        .set({ clientCredential: message.credential })
        .then(startTransport);
      pairingState = "paired";
      socket.close();
    } else if (message.type === "pairing.denied") {
      pairingState = "denied";
      socket.close();
    } else if (message.type === "pairing.expired") {
      pairingState = "expired";
      socket.close();
    } else if (message.type === "pairing.cancelled") {
      pairingState = "unpaired";
      socket.close();
    } else if (message.type === "pairing.error") {
      pairingState = "error";
      socket.close();
    }
  };
  socket.onerror = () => {
    pairingState = "error";
  };
  socket.onclose = () => {
    if (pairingSocket === socket) pairingSocket = null;
  };
}

function cancelPairing(): void {
  pairingSocket?.send(
    JSON.stringify({ type: "pairing.cancel", protocol_version: 2 }),
  );
  pairingState = "unpaired";
}

function handleSourceCommand(command: SourceCommand): void {
  const source = [...sources.values()].find(
    (candidate) => candidate.tabInstanceId === command.tab_instance_id,
  );
  if (!source) {
    sendCommandAck(command, "failed", "producer_disconnected");
    return;
  }
  source.sourceId = command.source_id;
  source.sourceEpochId = command.source_epoch_id;
  source.sessionId = command.session_id;
  const sent = postToCaptureFrame(source.tabId, {
    type: command.type,
    commandId: command.command_id,
    sourceId: command.source_id,
    sourceEpochId: command.source_epoch_id,
  });
  if (!sent) sendCommandAck(command, "failed", "producer_disconnected");
  void persistCoordinator();
}

function sendCommandAck(
  command: SourceCommand,
  result: SourceCommandAck["result"],
  errorCode?: string,
): void {
  transport?.sendControl({
    type: "source.command_ack",
    protocol_version: 2,
    command_id: command.command_id,
    source_id: command.source_id,
    source_epoch_id: command.source_epoch_id,
    result,
    ...(errorCode ? { error_code: errorCode } : {}),
  });
}

async function reportSourceUnavailable(source: SourceRuntime): Promise<void> {
  if (!transport || !source.sourceId) return;
  source.health = "unavailable";
  source.lastEventAt = new Date().toISOString();
  clientSequence += 1;
  await transport.enqueue({
    type: "source.health",
    protocol_version: 2,
    event_id: crypto.randomUUID(),
    client_seq: clientSequence,
    source_id: source.sourceId,
    source_epoch_id: source.sourceEpochId,
    health_status: "unavailable",
    error_code: "producer_disconnected",
    dropped_event_count: transportState.dropped,
    observed_at: source.lastEventAt,
  });
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
  const tabPorts =
    ports.get(tabId) ??
    new Map<number, ReturnType<typeof backgroundApi.runtime.connect>>();
  tabPorts.set(frameId, port);
  ports.set(tabId, tabPorts);
  port.onDisconnect.addListener(() => {
    if (ports.get(tabId)?.get(frameId) === port)
      ports.get(tabId)?.delete(frameId);
    if (ports.get(tabId)?.size === 0) {
      ports.delete(tabId);
      const source = sources.get(tabId);
      if (source) void reportSourceUnavailable(source);
    }
    frameElection.disconnected(tabId, frameId);
  });
  port.onMessage.addListener((rawMessage) => {
    const message = messageRecord(rawMessage);
    if (message.type === "adapter.discovered") {
      queueAdapterMessage(() => handleDiscovery(tabId, frameId, message));
    } else if (message.type === "adapter.status") {
      queueAdapterMessage(() => handleAdapterStatus(tabId, frameId, message));
    } else if (message.type === "adapter.utterance") {
      queueAdapterMessage(() => handleUtterance(tabId, frameId, message));
    } else if (message.type === "adapter.command_ack") {
      queueAdapterMessage(() => handleAdapterCommandAck(tabId, message));
    } else if (message.type === "diagnostics.bundle") {
      void downloadDiagnostic(message.bundle);
    }
  });
});

async function handleDiscovery(
  tabId: number,
  frameId: number,
  message: Record<string, unknown>,
): Promise<void> {
  if (frameId !== 0 && sources.has(tabId)) return;
  const current = sources.get(tabId);
  const source: SourceRuntime = {
    tabId,
    tabInstanceId: current?.tabInstanceId ?? crypto.randomUUID(),
    producerEpochId: String(message.producerEpochId),
    platform: message.platform as SourceRuntime["platform"],
    activityKey:
      typeof message.activityKey === "string" ? message.activityKey : undefined,
    health: message.supported === false ? "unavailable" : "waiting",
    speaker: "unknown",
    lastEventAt: new Date().toISOString(),
  };
  sources.set(tabId, source);
  await persistCoordinator();
  await announceSource(source);
}

async function announceSource(source: SourceRuntime): Promise<void> {
  if (!transport || transport.state().daemon !== "connected") return;
  const observedAt = source.lastEventAt ?? new Date().toISOString();
  clientSequence += 1;
  const event: SourceDiscovered = {
    type: "source.discovered",
    protocol_version: 2,
    event_id: crypto.randomUUID(),
    client_seq: clientSequence,
    tab_instance_id: source.tabInstanceId,
    producer_epoch_id: source.producerEpochId,
    platform: source.platform,
    activity_key: source.activityKey,
    driver_id:
      source.platform === "synthetic"
        ? "synthetic_captions"
        : "browser_captions",
    driver_version: extensionVersion,
    capabilities: [
      "captions",
      "speaker_labels",
      "daemon_source_control",
      "normalized_evidence",
    ],
    health_status: source.health,
    observed_at: observedAt,
  };
  discoveryRequests.set(event.event_id, source.tabId);
  await transport.enqueue(event);
}

async function handleAdapterStatus(
  tabId: number,
  frameId: number,
  message: Record<string, unknown>,
): Promise<void> {
  const source = sources.get(tabId);
  if (!source || !source.sourceId || !transport) return;
  if (
    !frameElection.acceptStatus(
      tabId,
      frameId,
      String(message.captionsStatus ?? "unknown"),
      Number(message.confidence ?? 0),
    )
  ) {
    return;
  }
  source.health =
    message.captionsStatus === "error"
      ? "degraded"
      : message.captionsStatus === "unavailable"
        ? "unavailable"
        : message.captionsStatus === "capturing"
          ? "available"
          : "waiting";
  source.speaker = String(message.speakerDetection ?? "unknown");
  source.lastEventAt = new Date().toISOString();
  clientSequence += 1;
  const event: SourceHealth = {
    type: "source.health",
    protocol_version: 2,
    event_id: crypto.randomUUID(),
    client_seq: clientSequence,
    source_id: source.sourceId,
    source_epoch_id: source.sourceEpochId,
    health_status: source.health,
    dropped_event_count: transportState.dropped,
    observed_at: source.lastEventAt,
  };
  await transport.enqueue(event);
  await persistCoordinator();
}

async function handleUtterance(
  tabId: number,
  frameId: number,
  message: Record<string, unknown>,
): Promise<void> {
  const source = sources.get(tabId);
  if (
    !source?.sourceId ||
    !source.sourceEpochId ||
    !source.sessionId ||
    !transport
  )
    return;
  if (!frameElection.acceptUtterance(tabId, frameId)) return;
  clientSequence += 1;
  source.lastEventAt = new Date().toISOString();
  const sessionStartedAt = Date.parse(
    String(transportState.session?.started_at ?? ""),
  );
  const observedAt = Date.parse(
    String(message.observedAt ?? source.lastEventAt),
  );
  const offset = Number.isFinite(sessionStartedAt)
    ? Math.max(0, observedAt - sessionStartedAt) * 1000
    : 0;
  const common = {
    protocol_version: 2 as const,
    event_id: crypto.randomUUID(),
    source_id: source.sourceId,
    source_epoch_id: source.sourceEpochId,
    client_seq: clientSequence,
    utterance_id: String(message.utteranceId),
    revision: Number(message.revision),
    speaker: typeof message.speaker === "string" ? message.speaker : null,
    text: String(message.text),
    session_offset_us: offset,
    source_time_us: Math.max(0, Math.round(performance.now() * 1000)),
  };
  const event: CaptionUpsert | CaptionFinalize =
    message.eventType === "finalize"
      ? { ...common, type: "caption.finalize" }
      : { ...common, type: "caption.upsert" };
  await transport.enqueue(event);
  await persistCoordinator();
}

async function handleAdapterCommandAck(
  tabId: number,
  message: Record<string, unknown>,
): Promise<void> {
  const source = sources.get(tabId);
  if (!source?.sourceId || !source.sourceEpochId) return;
  transport?.sendControl({
    type: "source.command_ack",
    protocol_version: 2,
    command_id: String(message.commandId),
    source_id: source.sourceId,
    source_epoch_id: source.sourceEpochId,
    result:
      message.result === "finalized"
        ? "finalized"
        : message.result === "failed"
          ? "failed"
          : "started",
    ...(typeof message.errorCode === "string"
      ? { error_code: message.errorCode }
      : {}),
  });
  if (message.result === "finalized") {
    source.sourceEpochId = undefined;
    source.sessionId = undefined;
  }
  await persistCoordinator();
}

async function downloadDiagnostic(bundle: unknown): Promise<void> {
  const encoded = encodeURIComponent(JSON.stringify(bundle, null, 2));
  await backgroundApi.downloads.download({
    url: `data:application/json;charset=utf-8,${encoded}`,
    filename: `elsewise-caption-diagnostic-${Date.now()}.json`,
    saveAs: true,
  });
}

backgroundApi.tabs.onRemoved.addListener((tabId) => {
  const source = sources.get(tabId);
  if (source) void reportSourceUnavailable(source);
  sources.delete(tabId);
  ports.delete(tabId);
  frameElection.clear(tabId);
  void persistCoordinator();
});

backgroundApi.runtime.onMessage.addListener(
  (rawMessage, _sender, sendResponse) => {
    const message = messageRecord(rawMessage);
    void (async () => {
      await initialization;
      if (message.type === "popup.status") sendResponse(status());
      if (message.type === "pairing.begin") {
        await beginPairing();
        sendResponse(status());
      }
      if (message.type === "pairing.cancel") {
        cancelPairing();
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
