import themeTokens from "../../shared/theme-tokens.json";

export type UiTheme = "dark" | "light";

export const THEME_STORAGE_KEY = "elsewise-ui-theme";

export function isUiTheme(value: unknown): value is UiTheme {
  return value === "dark" || value === "light";
}

export function readCachedTheme(
  storage: Pick<Storage, "getItem"> = localStorage,
): UiTheme {
  try {
    const value = storage.getItem(THEME_STORAGE_KEY);
    return isUiTheme(value) ? value : "dark";
  } catch {
    return "dark";
  }
}

export function cacheTheme(
  theme: UiTheme,
  storage: Pick<Storage, "setItem"> = localStorage,
): void {
  try {
    storage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // A blocked browser store must not prevent theme switching.
  }
}

export function applyTheme(
  theme: UiTheme,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  for (const [name, value] of Object.entries(themeTokens[theme])) {
    root.style.setProperty(`--color-${name.replaceAll("_", "-")}`, value);
  }
}
