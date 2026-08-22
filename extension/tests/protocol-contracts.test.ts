import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { MAX_CAPTION_TEXT_LENGTH } from "../src/protocol/limits";
import type { ProtocolMessageType } from "../src/protocol/models";
import { validateProtocolMessage } from "../src/protocol/validators";

interface FixtureCase {
  file: string;
  schema: ProtocolMessageType;
  valid: boolean;
}

const protocolRoot = fileURLToPath(new URL("../../protocol/", import.meta.url));
const manifest = JSON.parse(
  readFileSync(`${protocolRoot}/fixtures/manifest.json`, "utf8"),
) as {
  cases: FixtureCase[];
};

describe("protocol contract parity", () => {
  for (const fixtureCase of manifest.cases) {
    it(`${fixtureCase.valid ? "accepts" : "rejects"} ${fixtureCase.file}`, () => {
      const payload: unknown = JSON.parse(
        readFileSync(`${protocolRoot}/fixtures/${fixtureCase.file}`, "utf8"),
      );
      expect(validateProtocolMessage(fixtureCase.schema, payload).valid).toBe(
        fixtureCase.valid,
      );
    });
  }

  it("rejects caption text beyond the hard limit", () => {
    const payload = JSON.parse(
      readFileSync(
        `${protocolRoot}/fixtures/valid/utterance.upsert.json`,
        "utf8",
      ),
    ) as Record<string, unknown>;
    payload.text = "x".repeat(MAX_CAPTION_TEXT_LENGTH + 1);
    expect(validateProtocolMessage("utterance.upsert", payload).valid).toBe(
      false,
    );
  });
});
