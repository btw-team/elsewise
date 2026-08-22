import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import {
  FakeWebSocket,
  apiPayload,
  globalSettings,
  installAppTestHarness,
  providerHealth,
  snapshot,
} from "./appTestHarness";

installAppTestHarness();

describe("App live", () => {
  it("applies simple live deltas without requesting another snapshot", async () => {
    render(<App />);
    await screen.findByText(/Safe transcript/);
    const snapshotsBefore = vi
      .mocked(fetch)
      .mock.calls.filter(([path]) =>
        String(path).endsWith("/api/snapshot"),
      ).length;
    FakeWebSocket.instances.at(-1)?.receive({
      type: "ui.event",
      protocol_version: 1,
      event_id: 5,
      event_type: "utterance.created",
      aggregate_id: "utterance-2",
      created_at: "2026-08-13T10:03:00Z",
      payload: {
        ...snapshot.utterances[0],
        id: "utterance-2",
        utterance_id: "caption-2",
        text: "Direct live delta",
        first_client_seq: 3,
        last_client_seq: 3,
      },
    });
    expect(await screen.findByText("Direct live delta")).toBeInTheDocument();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.filter(([path]) => String(path).endsWith("/api/snapshot")),
    ).toHaveLength(snapshotsBefore);
  });

  it("renders live session state and transcript as escaped text", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Product planning" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Safe transcript/)).toBeInTheDocument();
    const segmentTimestamp = new Intl.DateTimeFormat("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(snapshot.segments[0]!.started_at));
    expect(
      screen.getByText(`Segment 1 · ${segmentTimestamp}`),
    ).toBeInTheDocument();
    const ownSpeaker = screen.getByText("Speaker A");
    expect(ownSpeaker).toHaveClass("speaker-name");
    expect(ownSpeaker.closest("article")).toHaveClass("speaker-self");
    expect(screen.queryByText(/You ·/)).not.toBeInTheDocument();
    expect(document.querySelector(".utterance img")).toBeNull();
    expect(screen.getByText("listening…")).toBeInTheDocument();
    await act(async () => undefined);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(document.querySelector(".connection-dot")).toBeNull();
    const reconnect = screen.getByRole("button", {
      name: "Reload page and reconnect · Daemon: Connected",
    });
    expect(reconnect).toHaveClass("brand-icon-frame", "online");
    expect(reconnect).toHaveAttribute(
      "title",
      "Reload page and reconnect · Connected",
    );
    expect(
      document.querySelectorAll(".sidebar-health .health-dot.ready"),
    ).toHaveLength(3);
  });

  it("loads stopped-session utterances from session detail", async () => {
    const truncated = structuredClone(snapshot);
    truncated.sessions[0]!.recording_status = "stopped";
    const historical = structuredClone(snapshot.utterances[0]!);
    historical.final = true;
    truncated.utterances = [historical];

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, truncated);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    expect(await screen.findByText(/Safe transcript/)).toBeInTheDocument();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/sessions/session-1/detail",
      expect.any(Object),
    );
  });

  it("moves session controls and health into the requested shared bars", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });

    const header = document.querySelector(".session-header");
    const sidebar = document.querySelector(".session-sidebar");
    const actionBar = document.querySelector(".action-bar");
    expect(header).not.toBeNull();
    expect(sidebar).not.toBeNull();
    expect(actionBar).not.toBeNull();

    const headerButtons = within(header as HTMLElement).getAllByRole("button");
    expect(
      headerButtons.map(
        (button) => button.getAttribute("aria-label") ?? button.textContent,
      ),
    ).toEqual([
      "Stop session",
      "Edit session",
      "Export Markdown",
      "Delete session",
    ]);
    expect(headerButtons[1]).toHaveClass("session-subtle-button");
    expect(headerButtons[2]).toHaveClass("session-subtle-button");
    expect(
      within(sidebar as HTMLElement).getByLabelText("System status"),
    ).toBeInTheDocument();
    expect(
      within(sidebar as HTMLElement).queryByText("Fallback directory"),
    ).not.toBeInTheDocument();
    expect(
      within(
        document.querySelector(".agent-panel > header") as HTMLElement,
      ).getByText("Fallback directory"),
    ).toBeInTheDocument();
    expect(
      within(actionBar as HTMLElement).getByRole("button", { name: "Summary" }),
    ).toBeInTheDocument();
    expect(
      within(actionBar as HTMLElement).queryByRole("button", { name: "Risks" }),
    ).not.toBeInTheDocument();
    expect(
      within(actionBar as HTMLElement).getByRole("button", { name: "Actions" }),
    ).toBe(actionBar?.lastElementChild);
    expect(
      within(actionBar as HTMLElement).getByRole("button", { name: "Actions" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit session" })).toBeDisabled();
    expect(screen.getByText("Google meet")).toBeInTheDocument();
  });

  it("resizes columns and toggles the transcript from the shared action bar", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });

    const shell = document.querySelector(".app-shell") as HTMLElement;
    const sidebar = document.querySelector(".session-sidebar") as HTMLElement;
    const workspace = document.querySelector(".workspace") as HTMLElement;
    vi.spyOn(shell, "getBoundingClientRect").mockReturnValue({
      left: 0,
      right: 1080,
    } as DOMRect);
    vi.spyOn(sidebar, "getBoundingClientRect").mockReturnValue({
      left: 0,
      right: 220,
    } as DOMRect);
    vi.spyOn(workspace, "getBoundingClientRect").mockReturnValue({
      left: 220,
      right: 650,
      width: 430,
    } as DOMRect);
    const resizer = screen.getByRole("separator", {
      name: "Resize transcript and agent columns",
    });
    expect(resizer).toHaveAttribute("aria-valuenow", "50");
    fireEvent.keyDown(resizer, { key: "ArrowRight" });
    expect(resizer).not.toHaveAttribute("aria-valuenow", "50");

    fireEvent.click(
      screen.getByRole("button", { name: "Hide live transcript" }),
    );
    expect(shell).toHaveClass("transcript-hidden");
    expect(
      screen.getByRole("button", { name: "Show live transcript" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.queryByRole("separator", {
        name: "Resize transcript and agent columns",
      }),
    ).not.toBeInTheDocument();
  });

  it("shows streamed agent output and sends a configured action", async () => {
    render(<App />);
    expect(await screen.findByText(/Streaming answer/)).toBeInTheDocument();
    expect(document.querySelector(".agent-run script")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Summary" }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/sessions/session-1/agent-runs",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("sends a free prompt with Enter and keeps its composer outside the result scroll", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    const prompt = screen.getByRole("textbox", { name: "Free prompt" });
    expect(
      prompt.closest(".agent-composer")?.previousElementSibling,
    ).toHaveClass("agent-scroll");

    fireEvent.change(prompt, {
      target: { value: "  What should we do next?  " },
    });
    fireEvent.keyDown(prompt, { key: "Enter" });

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/sessions/session-1/agent-runs",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ prompt: "What should we do next?" }),
        }),
      ),
    );
    await waitFor(() => expect(prompt).toHaveValue(""));
    expect(screen.getByRole("button", { name: "Send prompt" })).toBeDisabled();
  });

  it("keeps long transcripts bounded and cursor-loads earlier utterances", async () => {
    const truncated = structuredClone(snapshot);
    truncated.utterances_truncated = true;
    const earliest = structuredClone(truncated.utterances[0]!);
    earliest.id = "utterance-earliest";
    earliest.utterance_id = "caption-earliest";
    earliest.text = "Earlier transcript page";
    earliest.first_observed_at = "2026-08-13T09:59:00Z";
    earliest.last_observed_at = "2026-08-13T09:59:00Z";
    earliest.first_client_seq = 0;
    earliest.last_client_seq = 0;
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.includes("/utterances?")
        ? { items: [earliest], next_cursor: null, has_more: false }
        : path.endsWith("/api/agent/providers")
          ? providerHealth
          : path.endsWith("/api/settings")
            ? globalSettings
            : apiPayload(path, truncated);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Load earlier transcript" }),
    );
    expect(
      await screen.findByText("Earlier transcript page"),
    ).toBeInTheDocument();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/sessions/session-1/utterances?cursor=older-utterances&limit=500",
      ),
      expect.any(Object),
    );
  });
});
