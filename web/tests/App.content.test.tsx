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

describe("App content", () => {
  it.each([
    ["stopped", "Stopped"],
    ["starting", "Starting…"],
    ["ready", "Ready"],
    ["unavailable", "Unavailable"],
    ["error", "Error"],
  ] as const)(
    "renders the Codex %s health state distinctly",
    async (status, label) => {
      vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
        const path = String(input);
        const payload = path.endsWith("/api/agent/providers")
          ? {
              providers: providerHealth.providers.map((provider) =>
                provider.id === "codex"
                  ? {
                      ...provider,
                      status,
                      version: status === "ready" ? "test" : null,
                      authenticated: status === "ready" ? true : null,
                      message:
                        status === "error" ? "Codex app-server exited." : null,
                    }
                  : provider,
              ),
            }
          : path.endsWith("/api/settings")
            ? globalSettings
            : apiPayload(path, snapshot);
        return { ok: true, status: 200, json: async () => payload } as Response;
      });

      render(<App />);

      await waitFor(() =>
        expect(
          document.querySelector(`.agent-status.${status}`),
        ).toHaveTextContent(label),
      );
      const codexRow = Array.from(
        document.querySelectorAll(".sidebar-health > div"),
      ).find((row) => row.querySelector("dt")?.textContent === "Agent");
      expect(
        codexRow?.querySelector(`.health-dot.${status}`)?.parentElement,
      ).toHaveTextContent(label);
    },
  );

  it("opens the localized About modal from the compact sidebar button", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });

    const sidebar = document.querySelector(".session-sidebar") as HTMLElement;
    const controls = sidebar.querySelector(".sidebar-footer-actions");
    const aboutButton = within(sidebar).getByRole("button", { name: "About" });
    const settingsButton = within(sidebar).getByRole("button", {
      name: "Settings",
    });
    expect(controls?.firstElementChild).toBe(aboutButton);
    expect(controls?.lastElementChild).toBe(settingsButton);
    expect(aboutButton).toHaveTextContent("");
    expect(aboutButton.querySelector("svg")).toBeInTheDocument();

    fireEvent.click(aboutButton);

    const dialog = await screen.findByRole("dialog", {
      name: "About Elsewise",
    });
    expect(
      within(dialog).queryByRole("heading", { name: "About Elsewise" }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Close" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("v0.1.2")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", { name: "btw-team/elsewise" }),
    ).toHaveAttribute("href", "https://github.com/btw-team/elsewise");
    expect(
      within(dialog).getByRole("link", { name: "Apache License 2.0" }),
    ).toHaveAttribute("href", "https://www.apache.org/licenses/LICENSE-2.0");
    expect(
      within(dialog).getByText(/Copyright © 2026 Evgenii Gerasimenko/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("TypeScript")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Local-first: captions and session data stay on this machine.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/requires Codex and\/or Claude Code/),
    ).toBeInTheDocument();
    expect(dialog.querySelector(".about-maintainer img")).toHaveAttribute(
      "src",
      expect.stringContaining("white-bunny-avatar.png"),
    );
    const supportLink = within(dialog).getByRole("link", {
      name: "If Elsewise is useful to you, I’d be grateful for your support.",
    });
    expect(supportLink).toHaveAttribute("href", "https://ko-fi.com/tychh");
    expect(
      within(dialog).getByText(/Created and maintained by/),
    ).toHaveTextContent("Created and maintained by btw.team/tychh");
    expect(supportLink.querySelector("img")).toHaveAttribute(
      "src",
      expect.stringContaining("kofi-icon.png"),
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "About Elsewise" }),
    ).not.toBeInTheDocument();
  });

  it("renders About in the current non-English GUI language", async () => {
    globalSettings.ui_language = "ru";
    localStorage.setItem("elsewise-ui-language", "ru");
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });

    fireEvent.click(screen.getByRole("button", { name: "О программе" }));

    const dialog = await screen.findByRole("dialog", { name: "О Elsewise" });
    expect(
      within(dialog).getByText(/Если Elsewise вам полезен/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        /Подробности приведены в файлах LICENSE и NOTICE/,
      ),
    ).toBeInTheDocument();
  });

  it("renders basic Markdown in agent answers without rendering raw HTML", async () => {
    const markdownSnapshot = structuredClone(snapshot);
    markdownSnapshot.agent_messages[0]!.text = [
      "# Compact heading",
      "",
      "Regular **bold text** with `inline code`.",
      "",
      "- First item",
      "- Second item",
      "",
      "> Important quote",
      "",
      "[Safe link](https://example.com)",
      "",
      "```ts",
      "const answer = 42;",
      "```",
      "",
      '<script data-testid="unsafe-script">alert(1)</script>',
    ].join("\n");
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, markdownSnapshot);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);

    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Compact heading",
    });
    const answer = heading.closest(".agent-answer");
    expect(answer).toBeInTheDocument();
    expect(screen.getByText("bold text").tagName).toBe("STRONG");
    expect(screen.getByText("inline code").tagName).toBe("CODE");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(
      screen.getByText("Important quote").closest("blockquote"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("const answer = 42;").closest("pre"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Safe link" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(document.querySelector(".agent-answer script")).toBeNull();
    expect(answer).toHaveTextContent(/alert\(1\)/);
  });

  it("shows only the working directory name in the Agent header", async () => {
    const configured = structuredClone(snapshot);
    configured.sessions[0]!.agent_cwd_fallback = false;
    configured.sessions[0]!.resolved_agent_cwd =
      "/srv/workspaces/elsewise-project";
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, configured);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);

    const badge = await screen.findByText("elsewise-project");
    expect(badge).toHaveClass("agent-directory");
    expect(badge).toHaveAttribute("title", "/srv/workspaces/elsewise-project");
  });

  it("exports Markdown and shows the exact result directory", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Export Markdown" }));
    expect(
      await screen.findByText(/Exported to: \/safe\/exports\/session-1/),
    ).toBeInTheDocument();
  });
});
