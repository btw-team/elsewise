// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";

import {
  installZoomSpeakerBridge,
  zoomDisplayNameFromRoot,
} from "../src/content/zoom-speaker-bridge";

const flush = () =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, 0));

afterEach(() => {
  document.body.innerHTML = "";
});

describe("Zoom main-world speaker bridge", () => {
  it("copies only a normalized displayName from root-scoped React props", () => {
    const root = document.createElement("div");
    root.id = "live-transcription-subtitle";
    Object.defineProperty(root, "__reactProps$fixture", {
      value: {
        children: [
          {
            props: {
              displayName: "  Chu   Kimba  ",
              avatarUrl: "https://private.invalid/avatar.png",
            },
          },
        ],
      },
    });
    document.body.append(root);

    const stop = installZoomSpeakerBridge(document);
    expect(root.getAttribute("data-elsewise-speaker")).toBe("Chu Kimba");
    expect(root.outerHTML).not.toContain("private.invalid");
    stop();
  });

  it("updates the annotation after a React props change and DOM mutation", async () => {
    const root = document.createElement("div");
    root.id = "live-transcription-subtitle";
    const props = { children: [{ props: { displayName: "First name" } }] };
    Object.defineProperty(root, "__reactProps$fixture", { value: props });
    document.body.append(root);
    const stop = installZoomSpeakerBridge(document);

    props.children[0]!.props.displayName = "Second name";
    root.append(document.createTextNode("caption revision"));
    await flush();

    expect(root.getAttribute("data-elsewise-speaker")).toBe("Second name");
    stop();
  });

  it("uses a local fiber child fallback without traversing sibling roots", () => {
    const root = document.createElement("div");
    Object.defineProperty(root, "__reactFiber$fixture", {
      value: {
        child: { pendingProps: { displayName: "Local speaker" } },
        sibling: { pendingProps: { displayName: "Wrong sibling" } },
      },
    });

    expect(zoomDisplayNameFromRoot(root)).toBe("Local speaker");
  });

  it("rejects an overlong displayName", () => {
    const root = document.createElement("div");
    Object.defineProperty(root, "__reactProps$fixture", {
      value: { displayName: "x".repeat(513) },
    });

    expect(zoomDisplayNameFromRoot(root)).toBeNull();
  });
});
