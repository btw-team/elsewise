import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

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

  it("rejects evidence payloads beyond the hard field limit", () => {
    const payload = JSON.parse(
      readFileSync(
        `${protocolRoot}/fixtures/valid/evidence.emit.json`,
        "utf8",
      ),
    ) as Record<string, unknown>;
    payload.payload = Object.fromEntries(
      Array.from({ length: 65 }, (_, index) => [`field-${index}`, index]),
    );
    expect(validateProtocolMessage("evidence.emit", payload).valid).toBe(false);
  });
});
