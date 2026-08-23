import { describe, expect, it } from "vitest";

import { UI_CATALOGS, translate } from "../src/i18n/catalogs";
import { SUPPORTED_LANGUAGES } from "../src/i18n/languages";
import errorCatalog from "../../shared/api-errors.json";

describe("web localization", () => {
  it("has complete catalogs for all supported languages", () => {
    const englishKeys = Object.keys(UI_CATALOGS.en).sort();
    expect(Object.keys(UI_CATALOGS).sort()).toEqual(
      [...SUPPORTED_LANGUAGES].sort(),
    );
    for (const language of SUPPORTED_LANGUAGES) {
      expect(Object.keys(UI_CATALOGS[language]).sort()).toEqual(englishKeys);
      expect(translate(language, "settings")).not.toBe("");
    }
  });

  it("maps every stable API error to a complete localized catalog key", () => {
    const englishKeys = new Set(Object.keys(UI_CATALOGS.en));
    expect(new Set(errorCatalog.map((entry) => entry.code)).size).toBe(
      errorCatalog.length,
    );
    for (const entry of errorCatalog) {
      expect(englishKeys.has(entry.translation_key)).toBe(true);
      for (const language of SUPPORTED_LANGUAGES) {
        expect(
          UI_CATALOGS[language][
            entry.translation_key as keyof typeof UI_CATALOGS.en
          ],
        ).not.toBe("");
      }
    }
  });
});
