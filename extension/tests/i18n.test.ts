// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from "vitest";

import { interfaceLanguage, localizeDocument, message } from "../src/i18n";

type I18nApi = Pick<typeof chrome.i18n, "getMessage" | "getUILanguage">;

function fakeI18n(
  language: string,
  translations: Record<string, string> = {},
): I18nApi {
  return {
    getUILanguage: () => language,
    getMessage: (key: string) => translations[key] ?? "",
  } as I18nApi;
}

describe("extension localization", () => {
  beforeEach(() => {
    document.documentElement.lang = "en";
    document.body.innerHTML = '<h2 data-i18n="debug">Debug</h2>';
  });

  it("uses the browser UI language and localizes marked elements", () => {
    localizeDocument(document, fakeI18n("fr-FR", { debug: "Débogage" }));

    expect(document.documentElement.lang).toBe("fr");
    expect(document.querySelector("h2")?.textContent).toBe("Débogage");
  });

  it("supports regional variants and falls back for unsupported languages", () => {
    const unsupported = fakeI18n("pt-PT");

    expect(interfaceLanguage(fakeI18n("de-DE"))).toBe("de");
    expect(interfaceLanguage(fakeI18n("es-MX"))).toBe("es");
    expect(interfaceLanguage(fakeI18n("pt-BR"))).toBe("pt-BR");
    expect(interfaceLanguage(unsupported)).toBe("en");
    expect(message("openNewTab", unsupported)).toBe("Open in new tab");
  });
});
