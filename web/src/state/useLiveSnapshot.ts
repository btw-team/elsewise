import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type {
  ActionPreset,
  AgentMessage,
  AgentRun,
  ButtonDefinition,
  CaptureSource,
  SessionDetail,
  SessionSummary,
  GlobalSnapshot,
  UiEvent,
  Utterance,
} from "../types";

const emptySnapshot: GlobalSnapshot = {
  sessions: [],
  sources: [],
  buttons: [],
  action_presets: [],
  last_event_id: 0,
  pruned_through: 0,
};

function upsert<T>(
  items: T[],
  id: string,
  value: T,
  getId: (item: T) => string,
): T[] {
  const index = items.findIndex((item) => getId(item) === id);
  if (index < 0) return [...items, value];
  const next = [...items];
  next[index] = value;
  return next;
}

function applyGlobalEvent(
  snapshot: GlobalSnapshot,
  event: UiEvent,
): GlobalSnapshot | null {
  const payload = event.payload;
  if (event.event_type === "session.state") {
    const id = String(payload.id ?? event.aggregate_id ?? "");
    const sessions = payload.deleted
      ? snapshot.sessions.filter((session) => session.id !== id)
      : upsert(
          snapshot.sessions,
          id,
          payload as unknown as SessionSummary,
          (item) => item.id,
        );
    return { ...snapshot, sessions, last_event_id: event.event_id };
  }
  if (event.event_type === "source.status") {
    const id = String(payload.source_id ?? event.aggregate_id ?? "");
    const previous = snapshot.sources.find((source) => source.source_id === id);
    const source = {
      connected: true,
      meeting_title: null,
      meeting_key: null,
      tab_id: null,
      document_id: null,
      last_event_at: event.created_at,
      speaker_detection: null,
      ...previous,
      ...payload,
    } as CaptureSource;
    return {
      ...snapshot,
      sources: upsert(snapshot.sources, id, source, (item) => item.source_id),
      last_event_id: event.event_id,
    };
  }
  if (
    event.event_type === "button.created" ||
    event.event_type === "button.updated"
  ) {
    const button = payload as unknown as ButtonDefinition;
    return {
      ...snapshot,
      buttons: upsert(snapshot.buttons, button.id, button, (item) => item.id),
      last_event_id: event.event_id,
    };
  }
  if (event.event_type === "button.deleted") {
    return {
      ...snapshot,
      buttons: snapshot.buttons.filter((button) => button.id !== payload.id),
      last_event_id: event.event_id,
    };
  }
  if (
    event.event_type === "preset.created" ||
    event.event_type === "preset.updated"
  ) {
    const preset = payload as unknown as ActionPreset;
    return {
      ...snapshot,
      action_presets: upsert(
        snapshot.action_presets,
        preset.id,
        preset,
        (item) => item.id,
      ),
      last_event_id: event.event_id,
    };
  }
  if (event.event_type === "preset.deleted") return null;
  if (
    event.event_type.startsWith("utterance.") ||
    event.event_type.startsWith("agent.") ||
    event.event_type.startsWith("export.") ||
    event.event_type === "settings.changed"
  )
    return { ...snapshot, last_event_id: event.event_id };
  return null;
}

function applyDetailEvent(
  detail: SessionDetail | null,
  event: UiEvent,
): SessionDetail | null {
  if (!detail) return null;
  if (event.event_id <= detail.last_event_id) return detail;
  const payload = event.payload;
  if (event.event_type === "session.state") {
    if (
      payload.id !== detail.session.id &&
      event.aggregate_id !== detail.session.id
    )
      return detail;
    if (payload.deleted) return null;
    return {
      ...detail,
      session: payload as unknown as SessionSummary,
      last_event_id: event.event_id,
    };
  }
  if (event.event_type.startsWith("utterance.")) {
    if (payload.session_id !== detail.session.id) return detail;
    const utterance = payload as unknown as Utterance;
    return {
      ...detail,
      utterances: {
        ...detail.utterances,
        items: upsert(
          detail.utterances.items,
          utterance.id,
          utterance,
          (item) => item.id,
        ),
      },
      last_event_id: event.event_id,
    };
  }
  if (event.event_type === "agent.thread") {
    if (!detail.agent_thread || detail.agent_thread.id !== payload.id)
      return detail;
    return {
      ...detail,
      agent_thread: { ...detail.agent_thread, ...payload },
      last_event_id: event.event_id,
    } as SessionDetail;
  }
  if (event.event_type === "agent.delta") {
    const runId = String(payload.run_id ?? event.aggregate_id ?? "");
    if (!detail.agent_history.runs.some((run) => run.id === runId))
      return detail;
    const id = String(payload.id ?? `stream-${runId}`);
    const existing = detail.agent_history.messages.find(
      (message) => message.id === id,
    );
    const nextMessage = existing
      ? {
          ...existing,
          ...payload,
          text: `${existing.text}${String(payload.text ?? "")}`,
        }
      : ({
          ...payload,
          id,
          run_id: runId,
          text: String(payload.text ?? ""),
        } as unknown as AgentMessage);
    return {
      ...detail,
      agent_history: {
        ...detail.agent_history,
        messages: upsert(
          detail.agent_history.messages,
          id,
          nextMessage,
          (item) => item.id,
        ),
      },
      last_event_id: event.event_id,
    };
  }
  if (event.event_type.startsWith("agent.")) {
    const run = payload as unknown as AgentRun;
    if (run.session_id !== detail.session.id) return detail;
    return {
      ...detail,
      agent_history: {
        ...detail.agent_history,
        runs: upsert(detail.agent_history.runs, run.id, run, (item) => item.id),
      },
      last_event_id: event.event_id,
    };
  }
  return { ...detail, last_event_id: event.event_id };
}

export function useLiveSnapshot(selectedId: string | null): {
  snapshot: GlobalSnapshot;
  detail: SessionDetail | null;
  loading: boolean;
  connected: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  loadEarlierUtterances: () => Promise<number>;
  loadEarlierAgentHistory: () => Promise<number>;
} {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef(0);
  const latestRefresh = useRef(0);
  const refreshing = useRef(false);
  const bufferedEvents = useRef<UiEvent[]>([]);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;

  const refresh = useCallback(async () => {
    const refreshId = ++latestRefresh.current;
    if (!refreshing.current) bufferedEvents.current = [];
    refreshing.current = true;
    try {
      const global = await api.snapshot();
      const selected = selectedRef.current;
      const selectedDetail = selected
        ? await api.sessionDetail(selected)
        : null;
      if (refreshId !== latestRefresh.current) return;
      const pending = bufferedEvents.current
        .filter((event) => event.event_id > global.last_event_id)
        .sort((left, right) => left.event_id - right.event_id);
      bufferedEvents.current = [];
      refreshing.current = false;
      let nextGlobal = global;
      let nextDetail = selectedDetail;
      let complex = false;
      for (const event of pending) {
        const updated = applyGlobalEvent(nextGlobal, event);
        if (updated === null) complex = true;
        else nextGlobal = updated;
        nextDetail = applyDetailEvent(nextDetail, event);
      }
      cursor.current = Math.max(cursor.current, global.last_event_id);
      setSnapshot(nextGlobal);
      setDetail(nextDetail);
      setError(null);
      if (complex) window.setTimeout(() => void refresh(), 0);
    } catch (caught) {
      if (refreshId !== latestRefresh.current) return;
      const pending = bufferedEvents.current;
      bufferedEvents.current = [];
      refreshing.current = false;
      for (const event of pending) {
        setSnapshot((current) => applyGlobalEvent(current, event) ?? current);
        setDetail((current) => applyDetailEvent(current, event));
      }
      setError(caught instanceof Error ? caught.message : "Request failed");
    } finally {
      if (refreshId === latestRefresh.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    void api
      .sessionDetail(selectedId)
      .then((next) => {
        if (!active || selectedRef.current !== selectedId) return;
        setDetail((current) =>
          current?.session.id === selectedId &&
          current.last_event_id > next.last_event_id
            ? current
            : next,
        );
      })
      .catch((caught: unknown) => {
        if (active)
          setError(caught instanceof Error ? caught.message : "Request failed");
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  const loadEarlierUtterances = useCallback(async () => {
    const current = detail;
    if (!current?.utterances.next_cursor) return 0;
    const page = await api.utterances(
      current.session.id,
      current.utterances.next_cursor,
    );
    setDetail((value) =>
      value && value.session.id === current.session.id
        ? {
            ...value,
            utterances: {
              ...page,
              items: [...page.items, ...value.utterances.items],
            },
          }
        : value,
    );
    return page.items.length;
  }, [detail]);

  const loadEarlierAgentHistory = useCallback(async () => {
    const current = detail;
    if (!current?.agent_history.next_cursor) return 0;
    const page = await api.agentHistory(
      current.session.id,
      current.agent_history.next_cursor,
    );
    setDetail((value) =>
      value && value.session.id === current.session.id
        ? {
            ...value,
            agent_history: {
              ...page,
              runs: [...page.runs, ...value.agent_history.runs],
              messages: [...page.messages, ...value.agent_history.messages],
            },
          }
        : value,
    );
    return page.runs.length;
  }, [detail]);

  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    const connect = () => {
      if (!active) return;
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(
        `${scheme}://${location.host}/ws/ui?since=${cursor.current}`,
      );
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (message) => {
        let event: UiEvent;
        try {
          event = JSON.parse(message.data as string) as UiEvent;
        } catch {
          return;
        }
        if (event.event_type === "resync_required") {
          void refresh();
          return;
        }
        if (event.event_id <= cursor.current) return;
        cursor.current = event.event_id;
        if (refreshing.current) {
          bufferedEvents.current.push(event);
          return;
        }
        let complex = false;
        setSnapshot((current) => {
          const next = applyGlobalEvent(current, event);
          complex = next === null;
          return next ?? current;
        });
        setDetail((current) => applyDetailEvent(current, event));
        if (complex) void refresh();
      };
      socket.onclose = () => {
        setConnected(false);
        if (!active) return;
        reconnect = setTimeout(connect, Math.min(10_000, 500 * 2 ** attempt++));
      };
      socket.onerror = () => socket?.close();
    };
    void refresh().then(connect);
    return () => {
      active = false;
      if (reconnect) clearTimeout(reconnect);
      socket?.close();
    };
  }, [refresh]);

  return {
    snapshot,
    detail,
    loading,
    connected,
    error,
    refresh,
    loadEarlierUtterances,
    loadEarlierAgentHistory,
  };
}
