import { describe, expect, it } from "vitest";

import { ReconnectBackoff } from "../src/background/backoff";
import {
  PersistentEventBuffer,
  type BufferedEvent,
} from "../src/background/event-buffer";
import type { StorageAreaLike } from "../src/background/storage";
import { IngestTransport } from "../src/background/transport";

class MemoryStorage implements StorageAreaLike {
  values: Record<string, unknown> = {};
  async get(): Promise<Record<string, unknown>> {
    return { ...this.values };
  }
  async set(items: Record<string, unknown>): Promise<void> {
    Object.assign(this.values, items);
  }
}

class FakeSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: Record<string, unknown>[] = [];

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close(): void {
    this.readyState = 3;
  }
  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(message: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

const bufferedEvent: BufferedEvent = {
  type: "evidence.emit",
  protocol_version: 3,
  event_id: "00000000-0000-4000-8000-000000000001",
  source_id: "source",
  client_seq: 1,
  source_epoch_id: "epoch",
  capability: "captions",
  kind: "caption.partial",
  interval_start_us: 1,
  interval_end_us: 1,
  source_time_us: 1,
  timing_uncertainty_us: 0,
  provenance: "synthetic.dom",
  confidence: 1,
  payload: { utterance_id: "utterance-1", revision: 1, text: "hello" },
};

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("ingest transport", () => {
  it("resends pending events after hello and does not resend an acknowledged event after restart", async () => {
    const storage = new MemoryStorage();
    const buffer = new PersistentEventBuffer(storage);
    await buffer.enqueue(bufferedEvent, "session-1");
    const firstSocket = new FakeSocket();
    const first = new IngestTransport(
      buffer,
      "0123456789abcdef",
      "00000000-0000-4000-8000-000000000099",
      "0.1.2",
      () => firstSocket,
    );
    first.start();
    firstSocket.open();
    firstSocket.receive({
      type: "server.hello",
      session: { id: "session-1", recording_status: "running" },
    });
    await settle();
    expect(firstSocket.sent.map((message) => message.type)).toEqual([
      "client.hello",
      "evidence.emit",
    ]);
    firstSocket.receive({
      type: "event.ack",
      event_id: bufferedEvent.event_id,
      client_seq: 1,
    });
    await settle();
    firstSocket.receive({
      type: "heartbeat.ack",
      session: { id: "session-1", recording_status: "running" },
    });
    await settle();
    expect(first.state().session).toEqual({
      id: "session-1",
      recording_status: "running",
    });
    first.stop();

    const secondSocket = new FakeSocket();
    const restarted = new IngestTransport(
      new PersistentEventBuffer(storage),
      "0123456789abcdef",
      "00000000-0000-4000-8000-000000000099",
      "0.1.2",
      () => secondSocket,
    );
    restarted.start();
    secondSocket.open();
    secondSocket.receive({ type: "server.hello", session: null });
    await settle();
    expect(secondSocket.sent.map((message) => message.type)).toEqual([
      "client.hello",
    ]);
    restarted.stop();
  });

  it("uses capped exponential backoff with jitter", () => {
    const backoff = new ReconnectBackoff(() => 0, 100, 250);
    expect([
      backoff.nextDelay(),
      backoff.nextDelay(),
      backoff.nextDelay(),
    ]).toEqual([50, 100, 125]);
    backoff.reset();
    expect(backoff.nextDelay()).toBe(50);
  });

  it("paces a restored buffer so reconnect cannot exceed the ingest rate limit", async () => {
    const storage = new MemoryStorage();
    const buffer = new PersistentEventBuffer(storage);
    await buffer.enqueue(bufferedEvent, "session-1");
    await buffer.enqueue(
      {
        ...bufferedEvent,
        event_id: "00000000-0000-4000-8000-000000000002",
        client_seq: 2,
        interval_start_us: 2,
        interval_end_us: 2,
        source_time_us: 2,
        payload: { utterance_id: "utterance-2", revision: 1, text: "hello" },
      },
      "session-1",
    );
    const socket = new FakeSocket();
    const transport = new IngestTransport(
      buffer,
      "0123456789abcdef",
      "00000000-0000-4000-8000-000000000099",
      "0.1.2",
      () => socket,
      undefined,
      undefined,
      undefined,
      undefined,
      20,
    );

    transport.start();
    socket.open();
    socket.receive({
      type: "server.hello",
      session: { id: "session-1", recording_status: "running" },
    });
    await settle();
    expect(socket.sent.map((message) => message.type)).toEqual([
      "client.hello",
      "evidence.emit",
    ]);

    await new Promise((resolvePromise) => setTimeout(resolvePromise, 25));
    expect(socket.sent.map((message) => message.type)).toEqual([
      "client.hello",
      "evidence.emit",
      "evidence.emit",
    ]);
    transport.stop();
  });

  it("keeps recoverable errors and dead-letters permanent errors", async () => {
    const storage = new MemoryStorage();
    const buffer = new PersistentEventBuffer(storage);
    await buffer.enqueue(bufferedEvent, "session-1");
    const socket = new FakeSocket();
    const transport = new IngestTransport(
      buffer,
      "0123456789abcdef",
      "00000000-0000-4000-8000-000000000099",
      "0.1.2",
      () => socket,
    );
    transport.start();
    socket.open();
    socket.receive({
      type: "server.hello",
      session: { id: "session-1", recording_status: "running" },
    });
    await settle();
    socket.receive({
      type: "protocol.error",
      protocol_version: 3,
      event_id: bufferedEvent.event_id,
      client_seq: 1,
      code: "rate_limited",
      message: "Retry",
      recoverable: true,
    });
    await settle();
    expect((await buffer.snapshot()).events).toHaveLength(1);

    socket.receive({
      type: "protocol.error",
      protocol_version: 3,
      event_id: bufferedEvent.event_id,
      client_seq: 1,
      code: "invalid_message",
      message: "Permanent",
      recoverable: false,
    });
    await settle();
    const snapshot = await buffer.snapshot();
    expect(snapshot.events).toHaveLength(0);
    expect(snapshot.dead_letters).toEqual([
      expect.objectContaining({ reason_code: "invalid_message" }),
    ]);
    transport.stop();
  });
});
