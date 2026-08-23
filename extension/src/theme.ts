import themeTokens from "../../shared/theme-tokens.json";
import { webExtension } from "./browser-api";

export type UiTheme = "dark" | "light";
export const THEME_STORAGE_KEY = "elsewise-ui-theme";

export function isUiTheme(value: unknown): value is UiTheme {
  return value === "dark" || value === "light";
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

export async function loadTheme(): Promise<UiTheme> {
  const stored = await webExtension.storage.local.get(THEME_STORAGE_KEY);
  const value = stored[THEME_STORAGE_KEY];
  return isUiTheme(value) ? value : "dark";
}

export async function saveTheme(theme: UiTheme): Promise<void> {
  await webExtension.storage.local.set({ [THEME_STORAGE_KEY]: theme });
  applyTheme(theme);
}

export async function initializeTheme(
  onChange?: (theme: UiTheme) => void,
): Promise<UiTheme> {
  applyTheme("dark");
  const theme = await loadTheme();
  applyTheme(theme);
  onChange?.(theme);
  webExtension.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") return;
    const value = changes[THEME_STORAGE_KEY]?.newValue;
    const next = isUiTheme(value) ? value : "dark";
    applyTheme(next);
    onChange?.(next);
  });
  return theme;
}
