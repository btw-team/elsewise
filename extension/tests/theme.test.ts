import { describe, expect, it } from "vitest";

import { applyTheme, isUiTheme, THEME_STORAGE_KEY } from "../src/theme";

describe("extension theme", () => {
  it("uses the stable local-storage contract", () => {
    expect(THEME_STORAGE_KEY).toBe("elsewise-ui-theme");
    expect(isUiTheme("dark")).toBe(true);
    expect(isUiTheme("light")).toBe(true);
    expect(isUiTheme("system")).toBe(false);
  });

  it("applies the selected semantic palette to the shell", () => {
    const properties = new Map<string, string>();
    const root = {
      dataset: {} as Record<string, string>,
      style: {
        colorScheme: "",
        setProperty: (name: string, value: string) =>
          properties.set(name, value),
      },
    } as unknown as HTMLElement;
    applyTheme("light", root);
    expect(root.dataset.theme).toBe("light");
    expect(properties.get("--color-canvas")).toBe("#f7fafb");
  });
});
