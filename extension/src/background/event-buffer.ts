import {
  MAX_EXTENSION_BUFFER_BYTES,
  MAX_EXTENSION_BUFFER_EVENTS,
} from "../protocol/limits";
import type {
  SourceStatus,
  UtteranceFinalize,
  UtteranceUpsert,
} from "../protocol/models";
import type { StorageAreaLike } from "./storage";

export type BufferedEvent = SourceStatus | UtteranceUpsert | UtteranceFinalize;

export interface BufferedEnvelope {
  event: BufferedEvent;
  session_id: string | null;
}

export interface DeadLetter {
  at: string;
  event_type: BufferedEvent["type"];
  reason_code: string;
}

export interface BufferSnapshot {
  events: BufferedEnvelope[];
  dead_letters: DeadLetter[];
  dropped: number;
  pending_bytes: number;
  capacity_percent: number;
  full: boolean;
}

interface StoredBufferV2 {
  schema_version: 2;
  events: BufferedEnvelope[];
  dead_letters: DeadLetter[];
  dropped: number;
}

const STORAGE_KEY = "ingestBufferV2";
const MAX_DEAD_LETTERS = 20;

export class PersistentEventBuffer {
  #pendingOperation: Promise<void> = Promise.resolve();

  constructor(
    private readonly storage: StorageAreaLike,
    private readonly maxEvents = MAX_EXTENSION_BUFFER_EVENTS,
    private readonly maxBytes = MAX_EXTENSION_BUFFER_BYTES,
  ) {}

  async snapshot(): Promise<BufferSnapshot> {
    return this.#serialize(async () => this.#snapshot(await this.#read()));
  }

  async #read(): Promise<StoredBufferV2> {
    const result = await this.storage.get(STORAGE_KEY);
    const stored = result[STORAGE_KEY] as StoredBufferV2 | undefined;
    return stored?.schema_version === 2 && Array.isArray(stored.events)
      ? {
          schema_version: 2,
          events: [...stored.events],
          dead_letters: Array.isArray(stored.dead_letters)
            ? [...stored.dead_letters].slice(-MAX_DEAD_LETTERS)
            : [],
          dropped: stored.dropped ?? 0,
        }
      : { schema_version: 2, events: [], dead_letters: [], dropped: 0 };
  }

  #bytes(events: BufferedEnvelope[]): number {
    return new TextEncoder().encode(JSON.stringify(events)).byteLength;
  }

  #snapshot(state: StoredBufferV2): BufferSnapshot {
    const pendingBytes = this.#bytes(state.events);
    return {
      events: [...state.events],
      dead_letters: [...state.dead_letters],
      dropped: state.dropped,
      pending_bytes: pendingBytes,
      capacity_percent: Math.max(
        (state.events.length / this.maxEvents) * 100,
        (pendingBytes / this.maxBytes) * 100,
      ),
      full:
        state.events.length >= this.maxEvents || pendingBytes >= this.maxBytes,
    };
  }

  #deadLetter(
    state: StoredBufferV2,
    event: BufferedEvent,
    reasonCode: string,
  ): void {
    state.dead_letters = [
      ...state.dead_letters,
      {
        at: new Date().toISOString(),
        event_type: event.type,
        reason_code: reasonCode,
      },
    ].slice(-MAX_DEAD_LETTERS);
    state.dropped += 1;
  }

  async enqueue(
    event: BufferedEvent,
    sessionId: string | null = null,
  ): Promise<boolean> {
    return this.#serialize(async () => {
      const state = await this.#read();
      const envelope: BufferedEnvelope = {
        event,
        session_id: event.type === "source.status" ? null : sessionId,
      };
      const candidate = [...state.events, envelope];
      if (
        candidate.length > this.maxEvents ||
        this.#bytes(candidate) > this.maxBytes
      ) {
        this.#deadLetter(state, event, "buffer_full");
        await this.storage.set({ [STORAGE_KEY]: state });
        return false;
      }
      state.events = candidate;
      await this.storage.set({ [STORAGE_KEY]: state });
      return true;
    });
  }

  async acknowledge(eventId: string): Promise<void> {
    await this.#serialize(async () => {
      const state = await this.#read();
      state.events = state.events.filter(
        ({ event }) => event.event_id !== eventId,
      );
      await this.storage.set({ [STORAGE_KEY]: state });
    });
  }

  async reject(eventId: string, reasonCode: string): Promise<void> {
    await this.#serialize(async () => {
      const state = await this.#read();
      const rejected = state.events.find(
        ({ event }) => event.event_id === eventId,
      );
      if (!rejected) return;
      state.events = state.events.filter(
        ({ event }) => event.event_id !== eventId,
      );
      this.#deadLetter(state, rejected.event, reasonCode);
      await this.storage.set({ [STORAGE_KEY]: state });
    });
  }

  async reconcileSession(sessionId: string | null): Promise<void> {
    await this.#serialize(async () => {
      const state = await this.#read();
      const kept: BufferedEnvelope[] = [];
      for (const envelope of state.events) {
        if (envelope.event.type === "source.status") {
          kept.push(envelope);
        } else if (envelope.session_id === null) {
          this.#deadLetter(state, envelope.event, "missing_session_scope");
        } else if (envelope.session_id !== sessionId) {
          this.#deadLetter(state, envelope.event, "session_scope_changed");
        } else {
          kept.push(envelope);
        }
      }
      state.events = kept;
      await this.storage.set({ [STORAGE_KEY]: state });
    });
  }

  #serialize<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.#pendingOperation.then(operation, operation);
    this.#pendingOperation = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }
}
