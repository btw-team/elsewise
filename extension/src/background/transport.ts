import {
  HEARTBEAT_INTERVAL_SECONDS,
  PROTOCOL_VERSION,
} from "../protocol/limits";
import type { EventAck, ProtocolError } from "../protocol/models";
import { PersistentEventBuffer, type BufferedEvent } from "./event-buffer";
import { ReconnectBackoff } from "./backoff";

interface SocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
}

const SOCKET_OPEN = 1;
const RESEND_INTERVAL_MS = 10;

export interface TransportState {
  daemon: "connected" | "reconnecting" | "not_paired" | "unavailable";
  pending: number;
  dropped: number;
  pendingBytes: number;
  capacityPercent: number;
  bufferFull: boolean;
  session: Record<string, unknown> | null;
}

export class IngestTransport {
  #socket: SocketLike | null = null;
  #heartbeat: ReturnType<typeof setInterval> | null = null;
  #reconnect: ReturnType<typeof setTimeout> | null = null;
  #stopped = true;
  #state: TransportState = {
    daemon: "unavailable",
    pending: 0,
    dropped: 0,
    pendingBytes: 0,
    capacityPercent: 0,
    bufferFull: false,
    session: null,
  };

  constructor(
    private readonly buffer: PersistentEventBuffer,
    private readonly token: string,
    private readonly installationId: string,
    private readonly extensionVersion: string,
    private readonly socketFactory: (url: string) => SocketLike = (url) =>
      new WebSocket(url) as unknown as SocketLike,
    private readonly backoff = new ReconnectBackoff(),
    private readonly onState: (state: TransportState) => void = () => undefined,
    private readonly onAck: (ack: EventAck) => void = () => undefined,
    private readonly resendIntervalMs = RESEND_INTERVAL_MS,
  ) {}

  start(): void {
    this.#stopped = false;
    if (!this.token) {
      this.#setState({ daemon: "not_paired" });
      return;
    }
    this.#connect();
  }

  stop(): void {
    this.#stopped = true;
    if (this.#heartbeat) clearInterval(this.#heartbeat);
    if (this.#reconnect) clearTimeout(this.#reconnect);
    this.#socket?.close();
    this.#socket = null;
  }

  async enqueue(event: BufferedEvent): Promise<boolean> {
    const accepted = await this.buffer.enqueue(
      event,
      event.type === "source.status" ? null : this.#runningSessionId(),
    );
    await this.#refreshCounts();
    if (accepted && this.#socket?.readyState === SOCKET_OPEN) {
      this.#socket.send(JSON.stringify(event));
    }
    return accepted;
  }

  state(): TransportState {
    return { ...this.#state };
  }

  #connect(): void {
    if (this.#stopped) return;
    this.#setState({ daemon: "reconnecting" });
    const socket = this.socketFactory("ws://127.0.0.1:38473/ws/ingest");
    this.#socket = socket;
    socket.onopen = () => {
      socket.send(
        JSON.stringify({
          type: "client.hello",
          protocol_version: PROTOCOL_VERSION,
          role: "extension",
          token: this.token,
          installation_id: this.installationId,
          extension_version: this.extensionVersion,
        }),
      );
    };
    socket.onmessage = (event) => void this.#handleMessage(event.data);
    socket.onerror = () => this.#setState({ daemon: "unavailable" });
    socket.onclose = () => {
      if (this.#heartbeat) clearInterval(this.#heartbeat);
      this.#heartbeat = null;
      if (this.#stopped) return;
      this.#setState({ daemon: "reconnecting" });
      this.#reconnect = setTimeout(
        () => this.#connect(),
        this.backoff.nextDelay(),
      );
    };
  }

  async #handleMessage(raw: string): Promise<void> {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (message.type === "server.hello") {
      this.backoff.reset();
      this.#setState({
        daemon: "connected",
        session: (message.session as Record<string, unknown> | null) ?? null,
      });
      if (this.#heartbeat) clearInterval(this.#heartbeat);
      this.#heartbeat = setInterval(() => {
        if (this.#socket?.readyState === SOCKET_OPEN) {
          this.#socket.send(
            JSON.stringify({ type: "heartbeat", protocol_version: 1 }),
          );
        }
      }, HEARTBEAT_INTERVAL_SECONDS * 1000);
      await this.buffer.reconcileSession(this.#runningSessionId());
      await this.#resend();
      return;
    }
    if (message.type === "event.ack") {
      const ack = message as unknown as EventAck;
      this.onAck(ack);
      await this.buffer.acknowledge(ack.event_id);
      await this.#refreshCounts();
      return;
    }
    if (message.type === "heartbeat.ack") {
      this.#setState({
        session: (message.session as Record<string, unknown> | null) ?? null,
      });
      await this.buffer.reconcileSession(this.#runningSessionId());
      await this.#refreshCounts();
      return;
    }
    if (message.type === "protocol.error") {
      const error = message as unknown as ProtocolError;
      if (error.code === "unauthorized") {
        this.#setState({ daemon: "not_paired" });
        this.#stopped = true;
        this.#socket?.close();
      } else if (!error.recoverable && error.event_id) {
        await this.buffer.reject(error.event_id, error.code);
        await this.#refreshCounts();
      }
    }
  }

  async #resend(): Promise<void> {
    const snapshot = await this.buffer.snapshot();
    const socket = this.#socket;
    const events = snapshot.events.sort(
      (left, right) => left.event.client_seq - right.event.client_seq,
    );
    for (const [index, envelope] of events.entries()) {
      if (
        this.#stopped ||
        this.#socket !== socket ||
        socket?.readyState !== SOCKET_OPEN
      ) {
        break;
      }
      socket.send(JSON.stringify(envelope.event));
      if (index < events.length - 1 && this.resendIntervalMs > 0) {
        await new Promise((resolvePromise) =>
          setTimeout(resolvePromise, this.resendIntervalMs),
        );
      }
    }
    await this.#refreshCounts();
  }

  async #refreshCounts(): Promise<void> {
    const snapshot = await this.buffer.snapshot();
    this.#setState({
      pending: snapshot.events.length,
      dropped: snapshot.dropped,
      pendingBytes: snapshot.pending_bytes,
      capacityPercent: snapshot.capacity_percent,
      bufferFull: snapshot.full,
    });
  }

  #runningSessionId(): string | null {
    return this.#state.session?.recording_status === "running" &&
      typeof this.#state.session.id === "string"
      ? this.#state.session.id
      : null;
  }

  #setState(patch: Partial<TransportState>): void {
    this.#state = { ...this.#state, ...patch };
    this.onState({ ...this.#state });
  }
}
