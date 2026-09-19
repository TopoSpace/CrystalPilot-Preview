/** Contrast and persistence guards for every appearance combination. */
import { describe, expect, it } from "vitest";
import css from "../index.css?raw";
import html from "../../index.html?raw";
import { DEFAULT_PALETTE, PALETTES, normalizePalette, type Palette, type Theme } from "./theme";

type Tokens = Record<string, string>;

function block(source: string, header: RegExp): string {
  const m = header.exec(source);
  if (!m) throw new Error(`block not found: ${header}`);
  let depth = 0;
  for (let i = m.index + m[0].length - 1; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}") {
      depth--;
      if (depth === 0) return source.slice(m.index, i + 1);
    }
  }
  throw new Error(`unbalanced block: ${header}`);
}

function colorTokens(source: string): Tokens {
  const out: Tokens = {};
  for (const m of source.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    out[m[1]] = m[2];
  }
  return out;
}

export function luminance(hex: string): number {
  const c = hex.replace("#", "");
  const full = c.length === 3 ? c.split("").map((x) => x + x).join("") : c.slice(0, 6);
  const chan = [0, 2, 4].map((i) => {
    const v = parseInt(full.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2];
}

export function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const TEXT_ROLES = ["ink", "ink-2", "ink-3", "accent", "ok", "warn", "danger"] as const;
const AA = 4.5;
const SECONDARY_ROLES = ["ink-2", "ink-3"] as const;
const SECONDARY_MIN = 5;
const FILL_ROLES = ["accent-fill", "danger", "ok", "warn"] as const;

const anthropicLight = colorTokens(block(css, /@theme\s*\{/));
const anthropicDark = {
  ...anthropicLight,
  ...colorTokens(block(css, /\.dark\s*\{/)),
};

function paletteBlock(palette: Exclude<Palette, "anthropic">, theme: Theme): Tokens {
  const lightSelector = new RegExp(`html\\[data-palette="${palette}"\\]\\s*\\{`);
  const light = { ...anthropicLight, ...colorTokens(block(css, lightSelector)) };
  if (theme === "light") return light;
  const darkSelector = new RegExp(`html\\[data-palette="${palette}"\\]\\.dark\\s*\\{`);
  return { ...light, ...colorTokens(block(css, darkSelector)) };
}

function tokensFor(palette: Palette, theme: Theme): Tokens {
  if (palette === "anthropic") return theme === "light" ? anthropicLight : anthropicDark;
  return paletteBlock(palette, theme);
}

function worst(tokens: Tokens, role: string): { onBase: number; onRaised: number } {
  const fg = tokens[role];
  const onBase = Math.min(contrast(fg, tokens.bg), contrast(fg, tokens.surface));
  return { onBase, onRaised: contrast(fg, tokens.raised) };
}

const COMBINATIONS = PALETTES.flatMap((palette) =>
  (["light", "dark"] as const).map((theme) => [palette, theme, tokensFor(palette, theme)] as const),
);

describe.each(COMBINATIONS)("%s palette · %s contrast", (_palette, _theme, tokens) => {
  it("declares every semantic token", () => {
    for (const token of [...TEXT_ROLES, ...FILL_ROLES, "bg", "surface", "raised", "line"]) {
      expect(tokens[token], `--color-${token}`).toMatch(/^#/);
    }
  });

  for (const fill of FILL_ROLES) {
    it(`${fill} fill carries bg-coloured text at ${AA}:1`, () => {
      expect(contrast(tokens[fill], tokens.bg), `${fill} vs bg`).toBeGreaterThanOrEqual(AA);
    });
  }

  for (const role of SECONDARY_ROLES) {
    it(`${role} keeps ${SECONDARY_MIN}:1 on every surface`, () => {
      const { onBase, onRaised } = worst(tokens, role);
      expect(onBase, `${role} on bg/surface`).toBeGreaterThanOrEqual(SECONDARY_MIN);
      expect(onRaised, `${role} on raised`).toBeGreaterThanOrEqual(SECONDARY_MIN);
    });
  }

  for (const role of TEXT_ROLES) {
    it(`${role} keeps ${AA}:1 on every surface`, () => {
      const { onBase, onRaised } = worst(tokens, role);
      expect(onBase, `${role} on bg/surface`).toBeGreaterThanOrEqual(AA);
      expect(onRaised, `${role} on raised`).toBeGreaterThanOrEqual(AA);
    });
  }
});

describe("appearance persistence", () => {
  it("accepts only supported palettes and keeps the warm default", () => {
    for (const palette of PALETTES) expect(normalizePalette(palette)).toBe(palette);
    expect(normalizePalette("unknown")).toBe(DEFAULT_PALETTE);
    expect(normalizePalette(null)).toBe("anthropic");
  });

  it("applies validated mode, palette and font before the application script", () => {
    const bootstrap = html.indexOf("root.dataset.palette = palette");
    const application = html.indexOf('type="module"');
    expect(bootstrap).toBeGreaterThan(0);
    expect(application).toBeGreaterThan(bootstrap);
    expect(html).toContain('localStorage.getItem("crystalpilot-theme")');
    expect(html).toContain('localStorage.getItem("crystalpilot-palette")');
    expect(html).toContain('localStorage.getItem("crystalpilot-font-size")');
  });

  it("leaves shimmer text readable when motion is reduced", () => {
    expect(css).toMatch(/prefers-reduced-motion: reduce[\s\S]*\.shimmer-text\s*\{[\s\S]*background-image:\s*none;[\s\S]*color:\s*var\(--color-ink-3\)/);
  });
});
