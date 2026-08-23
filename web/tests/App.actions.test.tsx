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

describe("App actions", () => {
  it("edits actions in the dedicated two-tab drawer", async () => {
    const idle = structuredClone(snapshot);
    idle.sessions[0]!.recording_status = "idle";
    idle.sessions[0]!.agent_status = "not_started";
    vi.mocked(fetch).mockImplementation(async (input) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, idle);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    await screen.findByRole("dialog", { name: "Settings" });

    expect(
      screen.queryByRole("button", { name: "Create session" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Agent actions")).not.toBeInTheDocument();
    fireEvent.mouseDown(document.querySelector(".dialog-backdrop")!);

    const actionBar = document.querySelector(".action-bar") as HTMLElement;
    const actionTrigger = within(actionBar).getByRole("button", {
      name: "Actions",
    });
    expect(actionTrigger).toBe(actionBar.lastElementChild);
    fireEvent.click(actionTrigger);

    expect(
      screen.queryByRole("heading", { name: "Actions" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Close" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Action presets",
      "Agent actions",
    ]);
    expect(screen.getByRole("tab", { name: "Action presets" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.click(screen.getByRole("tab", { name: "Agent actions" }));
    expect(screen.getByLabelText("Button label")).toHaveValue("Summary");
    const actionSave = screen.getByRole("button", { name: "Save" });
    expect(actionSave.querySelector("svg")).not.toBeNull();
    expect(actionSave).not.toHaveClass("primary");
    expect(
      screen.getByRole("button", { name: "Delete" }).querySelector("svg"),
    ).not.toBeNull();
    const addAction = screen.getByRole("button", { name: "Add action" });
    expect(addAction.querySelector("svg")).not.toBeNull();
    fireEvent.click(addAction);
    expect(screen.queryByPlaceholderText("stable_key")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Button label")).toHaveValue("");

    fireEvent.click(screen.getByRole("tab", { name: "Action presets" }));
    expect(screen.getByRole("button", { name: "Save" })).not.toHaveClass(
      "primary",
    );
    expect(screen.getByLabelText("Preset name")).toBeDisabled();
    expect(screen.getByLabelText("Preset name")).toHaveValue("Default");
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add preset" }).querySelector("svg"),
    ).not.toBeNull();

    const included = screen.getByRole("heading", {
      name: "Actions in this preset",
    }).parentElement?.parentElement as HTMLElement;
    fireEvent.click(within(included).getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Action removed from preset. Save the preset to apply the change.",
    );
    expect(
      within(included).getByText("This preset has no actions."),
    ).toBeInTheDocument();
    const available = screen.getByRole("heading", {
      name: "Available actions",
    }).parentElement?.parentElement as HTMLElement;
    expect(
      within(available).getAllByRole("button", { name: "Add" }),
    ).toHaveLength(2);
  });

  it("allows editing actions and presets without a selected session", async () => {
    const empty = structuredClone(snapshot);
    empty.sessions = [];
    empty.utterances = [];
    empty.segments = [];
    empty.sources = [];
    empty.agent_threads = [];
    empty.agent_runs = [];
    empty.agent_messages = [];
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, empty);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    const actionButton = await screen.findByRole("button", { name: "Summary" });
    const actionsTrigger = screen.getByRole("button", { name: "Actions" });
    expect(actionButton).toBeDisabled();
    expect(actionsTrigger).toBeEnabled();

    fireEvent.click(actionsTrigger);
    expect(
      await screen.findByRole("dialog", { name: "Actions" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Action presets" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "Add preset" })).toBeEnabled();

    fireEvent.click(screen.getByRole("tab", { name: "Agent actions" }));
    expect(screen.getByRole("button", { name: "Add action" })).toBeEnabled();
  });

  it("creates an action without exposing a stable key", async () => {
    const idle = structuredClone(snapshot);
    idle.sessions[0]!.recording_status = "idle";
    idle.sessions[0]!.agent_status = "not_started";
    const created = {
      ...snapshot.buttons[1]!,
      id: "button-created",
      label: "Decisions",
      prompt_template: "Find the decisions",
    };
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      const path = String(input);
      const payload =
        path.endsWith("/api/buttons") && options?.method === "POST"
          ? created
          : path.endsWith("/api/agent/providers")
            ? providerHealth
            : path.endsWith("/api/settings")
              ? globalSettings
              : apiPayload(path, idle);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    fireEvent.click(await screen.findByRole("tab", { name: "Agent actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Add action" }));

    fireEvent.change(screen.getByLabelText("Button label"), {
      target: { value: "Decisions" },
    });
    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "Find the decisions" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/buttons",
        expect.objectContaining({
          method: "POST",
          body: expect.not.stringContaining('"key"'),
        }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Action saved.",
    );
  });

  it("confirms action and preset deletion with in-app dialogs", async () => {
    const idle = structuredClone(snapshot);
    idle.sessions[0]!.recording_status = "idle";
    idle.sessions[0]!.agent_status = "not_started";
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, idle);
      return {
        ok: true,
        status: options?.method === "DELETE" ? 204 : 200,
        json: async () => payload,
      } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    fireEvent.click(screen.getByRole("tab", { name: "Agent actions" }));
    const deleteAction = screen.getByRole("button", { name: "Delete" });
    deleteAction.focus();
    fireEvent.click(deleteAction);

    let dialog = screen.getByRole("alertdialog", {
      name: "Confirm deletion",
    });
    expect(
      within(dialog).getByText("Delete this global action button?"),
    ).toBeInTheDocument();
    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    const confirmDelete = within(dialog).getByRole("button", {
      name: "Delete",
    });
    const closeDialog = within(dialog).getByRole("button", { name: "Close" });
    closeDialog.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirmDelete);
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(closeDialog);
    expect(
      document.querySelector(".actions-drawer")?.parentElement,
    ).toHaveAttribute("inert");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(deleteAction);
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([, options]) => options?.method === "DELETE"),
    ).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "Action presets" }));
    fireEvent.click(screen.getByRole("button", { name: /Release/ }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    dialog = screen.getByRole("alertdialog", { name: "Confirm deletion" });
    expect(
      within(dialog).getByText("Delete this action preset?"),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([path, options]) =>
              String(path).endsWith("/api/action-presets/preset-release") &&
              options?.method === "DELETE",
          ),
      ).toBe(true),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Preset deleted.",
    );
  });

  it("uses the session preset for action buttons and falls back to Default", async () => {
    const release = structuredClone(snapshot);
    release.sessions[0]!.action_preset_id = "preset-release";
    vi.mocked(fetch).mockImplementationOnce(
      async (input) =>
        ({
          ok: true,
          status: 200,
          json: async () => apiPayload(String(input), release),
        }) as Response,
    );

    const { unmount } = render(<App />);
    await screen.findByRole("button", { name: "Risks" });
    expect(screen.queryByRole("button", { name: "Summary" })).toBeNull();
    unmount();

    const fallback = structuredClone(snapshot);
    fallback.sessions[0]!.action_preset_id = "missing-preset";
    vi.mocked(fetch).mockImplementationOnce(
      async (input) =>
        ({
          ok: true,
          status: 200,
          json: async () => apiPayload(String(input), fallback),
        }) as Response,
    );
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Summary" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Risks" })).toBeNull();
  });
});
