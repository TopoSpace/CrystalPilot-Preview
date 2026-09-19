import { describe, expect, it } from "vitest";
import {
  jsonToStringMap,
  PROVIDER_PRESETS,
  textToMap,
} from "./ProvidersSection";

describe("provider configuration form", () => {
  it("offers only Responses-compatible presets", () => {
    expect(PROVIDER_PRESETS.map((preset) => preset.label)).toEqual([
      "CrystalPilot Gateway",
      "OpenRouter",
      "OpenAI",
      "Responses-compatible",
    ]);
    expect(PROVIDER_PRESETS.find((preset) => preset.id === "openrouter")?.base_url)
      .toBe("https://openrouter.ai/api/v1");
  });

  it("parses strict header and environment mappings", () => {
    expect(textToMap("X-Title: CrystalPilot\nX-Tenant: CP_TENANT")).toEqual({
      "X-Title": "CrystalPilot",
      "X-Tenant": "CP_TENANT",
    });
    expect(() => textToMap("missing-value:")).toThrow();
    expect(() => textToMap("X-A: one\nX-A: two")).toThrow();
  });

  it("accepts only JSON objects with string query values", () => {
    expect(jsonToStringMap('{"api-version":"2026-01-01"}')).toEqual({
      "api-version": "2026-01-01",
    });
    expect(() => jsonToStringMap("[]")).toThrow();
    expect(() => jsonToStringMap('{"limit":2}')).toThrow();
  });
});
