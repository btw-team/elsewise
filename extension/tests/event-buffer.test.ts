import { describe, expect, it } from "vitest";

import {
  PersistentEventBuffer,
  type BufferedEvent,
} from "../src/background/event-buffer";
import type { StorageAreaLike } from "../src/background/storage";

class MemoryStorage implements StorageAreaLike {
  values: Record<string, unknown> = {};

  async get(): Promise<Record<string, unknown>> {
    return { ...this.values };
  }

  async set(items: Record<string, unknown>): Promise<void> {
    Object.assign(this.values, items);
  }
}

function event(sequence: number): BufferedEvent {
  return {
    type: "utterance.upsert",
    protocol_version: 1,
    event_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    source_id: "source",
    client_seq: sequence,
    platform: "synthetic",
    meeting_key: "harness",
    utterance_id: `utterance-${sequence}`,
    revision: 1,
    text: "hello",
    observed_at: "2026-08-13T12:00:00.000Z",
  };
}

describe("persistent event buffer", () => {
  it("preserves FIFO events across instances and acknowledges by stable event id", async () => {
    const storage = new MemoryStorage();
    const firstWorker = new PersistentEventBuffer(storage);
    await firstWorker.enqueue(event(1), "session-1");
    await firstWorker.enqueue(event(2), "session-1");

    const restartedWorker = new PersistentEventBuffer(storage);
    expect(
      (await restartedWorker.snapshot()).events.map(
        (item) => item.event.client_seq,
      ),
    ).toEqual([1, 2]);
    await restartedWorker.acknowledge(event(1).event_id);
    expect(
      (await restartedWorker.snapshot()).events.map(
        (item) => item.event.client_seq,
      ),
    ).toEqual([2]);
  });

  it("reports overflow instead of silently growing", async () => {
    const buffer = new PersistentEventBuffer(new MemoryStorage(), 1, 100_000);
    expect(await buffer.enqueue(event(1))).toBe(true);
    expect(await buffer.snapshot()).toMatchObject({
      full: true,
      capacity_percent: 100,
    });
    expect(await buffer.enqueue(event(2))).toBe(false);
    expect(await buffer.snapshot()).toMatchObject({
      dropped: 1,
      dead_letters: [expect.objectContaining({ reason_code: "buffer_full" })],
    });
  });

  it("serializes concurrent writes without losing events", async () => {
    const buffer = new PersistentEventBuffer(new MemoryStorage());

    await Promise.all([
      buffer.enqueue(event(1), "session-1"),
      buffer.enqueue(event(2), "session-1"),
      buffer.enqueue(event(3), "session-1"),
    ]);

    expect(
      (await buffer.snapshot()).events.map((item) => item.event.client_seq),
    ).toEqual([1, 2, 3]);
  });

  it("drops caption events outside their original running session", async () => {
    const buffer = new PersistentEventBuffer(new MemoryStorage());
    await buffer.enqueue(event(1), null);
    await buffer.enqueue(event(2), "session-1");
    await buffer.enqueue(event(3), "session-2");

    await buffer.reconcileSession("session-1");
    const snapshot = await buffer.snapshot();
    expect(snapshot.events.map(({ event: item }) => item.client_seq)).toEqual([
      2,
    ]);
    expect(snapshot.dead_letters).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ reason_code: "missing_session_scope" }),
        expect.objectContaining({ reason_code: "session_scope_changed" }),
      ]),
    );
    expect(JSON.stringify(snapshot.dead_letters)).not.toContain("hello");
  });

  it("bounds redacted dead letters", async () => {
    const buffer = new PersistentEventBuffer(new MemoryStorage());
    for (let sequence = 1; sequence <= 25; sequence += 1) {
      const item = event(sequence);
      await buffer.enqueue(item, "session-1");
      await buffer.reject(item.event_id, "invalid_message");
    }
    const snapshot = await buffer.snapshot();
    expect(snapshot.dead_letters).toHaveLength(20);
    expect(snapshot.dead_letters[0]?.event_type).toBe("utterance.upsert");
  });
});
