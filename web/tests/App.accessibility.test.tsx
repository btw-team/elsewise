import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import {
  apiPayload,
  globalSettings,
  installAppTestHarness,
  providerHealth,
  snapshot,
} from "./appTestHarness";

installAppTestHarness();

describe("App accessibility", () => {
  it("confirms session deletion with an in-app dialog", async () => {
    const stopped = structuredClone(snapshot);
    stopped.sessions[0]!.recording_status = "stopped";
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, stopped);
      return {
        ok: true,
        status: options?.method === "DELETE" ? 204 : 200,
        json: async () => payload,
      } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Delete session" }));

    const dialog = screen.getByRole("alertdialog", {
      name: "Confirm deletion",
    });
    expect(
      within(dialog).getByText("Permanently delete this session?"),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([path, options]) =>
              String(path).includes(
                "/api/sessions/session-1?confirm=session-1",
              ) && options?.method === "DELETE",
          ),
      ).toBe(true),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Session deleted.",
    );
  });

  it("confirms expanded agent permissions with an in-app dialog", async () => {
    const created = structuredClone(snapshot.sessions[0]!);
    created.recording_status = "idle";
    created.agent_status = "not_started";
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      const path = String(input);
      const payload =
        path.endsWith("/api/sessions") && options?.method === "POST"
          ? created
          : path.endsWith("/api/agent/providers")
            ? providerHealth
            : path.endsWith("/api/settings")
              ? globalSettings
              : apiPayload(path, snapshot);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    fireEvent.change(await screen.findByLabelText("Title"), {
      target: { value: "Permission test" },
    });
    fireEvent.click(screen.getByLabelText("Allow network access"));
    fireEvent.click(screen.getByRole("button", { name: "Create session" }));

    const dialog = screen.getByRole("alertdialog", {
      name: "Confirm permission changes",
    });
    expect(
      within(dialog).getByText(/This expands agent permissions/),
    ).toBeInTheDocument();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([path, options]) =>
            String(path).endsWith("/api/sessions") &&
            options?.method === "POST",
        ),
    ).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([path, options]) =>
              String(path).endsWith("/api/sessions") &&
              options?.method === "POST",
          ),
      ).toBe(true),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Session created.",
    );
  });
});
