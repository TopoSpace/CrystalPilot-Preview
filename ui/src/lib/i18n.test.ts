import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_LANGUAGE,
  LANGUAGE_HEADER,
  LANGUAGE_STORAGE_KEY,
  LANGUAGES,
  formatEffort,
  isLanguage,
  localeTag,
  readLanguage,
  setLanguage,
  t,
} from "./i18n";
import { en, zh } from "./strings";

// the unit tests run without a DOM; give the module the two browser globals it
// touches (the reload is skipped because `window` stays undefined)
const store = new Map<string, string>();
const fakeStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
};
const fakeDocument = { documentElement: { lang: "" } };

beforeAll(() => {
  vi.stubGlobal("localStorage", fakeStorage);
  vi.stubGlobal("document", fakeDocument);
});
afterAll(() => vi.unstubAllGlobals());
afterEach(() => store.clear());

/** Every leaf of the dictionaries: dotted key -> value. */
function leaves(obj: unknown, prefix = ""): Map<string, unknown> {
  const out = new Map<string, unknown>();
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        for (const [ik, iv] of leaves(v, key)) out.set(ik, iv);
      } else {
        out.set(key, v);
      }
    }
  }
  return out;
}

describe("interface language", () => {
  it("defaults to Chinese and validates stored values", () => {
    expect(DEFAULT_LANGUAGE).toBe("zh");
    expect(readLanguage()).toBe("zh");
    store.set(LANGUAGE_STORAGE_KEY, "fr");
    expect(readLanguage()).toBe("zh");
    store.set(LANGUAGE_STORAGE_KEY, "en");
    expect(readLanguage()).toBe("en");
    expect(isLanguage("en")).toBe(true);
    expect(isLanguage("EN")).toBe(false);
    expect(LANGUAGES).toEqual(["zh", "en"]);
    expect(LANGUAGE_HEADER).toBe("X-CrystalPilot-Language");
  });

  it("stores the choice and sets the document language", () => {
    setLanguage("en", { reload: false });
    expect(store.get(LANGUAGE_STORAGE_KEY)).toBe("en");
    expect(fakeDocument.documentElement.lang).toBe("en-US");
    setLanguage("zh", { reload: false });
    expect(fakeDocument.documentElement.lang).toBe("zh-CN");
    expect(localeTag("en")).toBe("en-US");
  });

  it("serves the Chinese dictionary on a default page load", () => {
    expect(t.settings).toBe(zh.settings);
    expect(formatEffort("xhigh")).toBe("极高");
    expect(formatEffort(null)).toBe("");
  });
});

describe("dictionaries", () => {
  it("carry the same keys in both languages, including nested records", () => {
    const zhKeys = [...leaves(zh).keys()].sort();
    const enKeys = [...leaves(en).keys()].sort();
    expect(enKeys).toEqual(zhKeys);
  });

  it("have a non-empty English value for every Chinese string", () => {
    const zhLeaves = leaves(zh);
    const empty: string[] = [];
    for (const [key, value] of leaves(en)) {
      const source = zhLeaves.get(key);
      if (typeof source === "string" && source.length > 0 && typeof value === "string" && value.length === 0) {
        // a few English strings are legitimately empty where the Chinese one is a
        // prefix or suffix that English does not need; they are listed on purpose
        if (!["selQuoteSuffix", "showEarlierRemainingPrefix"].includes(key)) empty.push(key);
      }
      if (typeof source === "function") expect(typeof value).toBe("function");
    }
    expect(empty).toEqual([]);
  });

  it("leave no Chinese characters in the English dictionary", () => {
    const cjk = /[一-鿿]/;
    const offenders: string[] = [];
    for (const [key, value] of leaves(en)) {
      // functions are checked by their source text, so every literal they can
      // return is covered whatever their parameters are
      const text = Array.isArray(value) ? value.join(" ") : String(value);
      if (cjk.test(text)) offenders.push(key);
    }
    expect(offenders).toEqual([]);
  });
});
