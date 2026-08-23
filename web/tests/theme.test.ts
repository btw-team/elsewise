import { describe, expect, it } from "vitest";

import { applyTheme, readCachedTheme } from "../src/theme";

describe("web theme bootstrap", () => {
  it("defaults invalid cached values to dark", () => {
    expect(readCachedTheme({ getItem: () => "system" })).toBe("dark");
  });

  it("applies semantic token variables and the DOM theme", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(
      document.documentElement.style.getPropertyValue("--color-canvas"),
    ).toBe("#f7fafb");
  });
});
