/** Persistent appearance settings. Colour mode and palette are independent:
 * mode controls light/dark while palette selects the semantic colour set.
 * index.html mirrors the validation and DOM attributes before first paint. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";
export const PALETTES = ["anthropic", "openai", "kimi"] as const;
export type Palette = (typeof PALETTES)[number];
export const DEFAULT_PALETTE: Palette = "anthropic";
export const FONT_SIZES = [13, 14, 15, 16] as const;
export type FontSize = (typeof FONT_SIZES)[number];
const DEFAULT_FONT: FontSize = 14;

export const THEME_STORAGE_KEY = "crystalpilot-theme";
export const PALETTE_STORAGE_KEY = "crystalpilot-palette";
export const FONT_SIZE_STORAGE_KEY = "crystalpilot-font-size";
export const PRESENTATION_STORAGE_KEY = "crystalpilot-presentation";
const DARK_QUERY = "(prefers-color-scheme: dark)";

interface ThemeContextValue {
  /** effective theme (system preference resolved) */
  theme: Theme;
  preference: ThemePreference;
  setPreference: (p: ThemePreference) => void;
  /** flips the effective theme (keeps working for the old toggle button) */
  toggle: () => void;
  palette: Palette;
  setPalette: (palette: Palette) => void;
  fontSize: FontSize;
  setFontSize: (n: FontSize) => void;
  presentation: boolean;
  setPresentation: (enabled: boolean) => void;
  presentationName: string;
  setPresentationName: (name: string) => void;
  brandName: string;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "light",
  preference: "system",
  setPreference: () => undefined,
  toggle: () => undefined,
  palette: DEFAULT_PALETTE,
  setPalette: () => undefined,
  fontSize: DEFAULT_FONT,
  setFontSize: () => undefined,
  presentation: false,
  setPresentation: () => undefined,
  presentationName: "",
  setPresentationName: () => undefined,
  brandName: "CrystalPilot",
});

function readPresentation(): { enabled: boolean; name: string } {
  try {
    const stored = JSON.parse(localStorage.getItem(PRESENTATION_STORAGE_KEY) ?? "{}");
    return { enabled: stored?.enabled === true, name: typeof stored?.name === "string" ? stored.name.slice(0, 48) : "" };
  } catch { return { enabled: false, name: "" }; }
}

function readStoredPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    return v === "dark" || v === "light" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

export function normalizePalette(value: string | null | undefined): Palette {
  return (PALETTES as readonly string[]).includes(value ?? "")
    ? (value as Palette)
    : DEFAULT_PALETTE;
}

function readStoredPalette(): Palette {
  try {
    return normalizePalette(localStorage.getItem(PALETTE_STORAGE_KEY));
  } catch {
    return DEFAULT_PALETTE;
  }
}

function readStoredFont(): FontSize {
  try {
    const n = Number(localStorage.getItem(FONT_SIZE_STORAGE_KEY));
    return (FONT_SIZES as readonly number[]).includes(n) ? (n as FontSize) : DEFAULT_FONT;
  } catch {
    return DEFAULT_FONT;
  }
}

function systemDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(DARK_QUERY).matches
    : false;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [presentationSettings, setPresentationSettings] = useState(readPresentation);
  const presentation = presentationSettings.enabled;
  const presentationName = presentationSettings.name;
  const brandName = presentation && presentationName.trim() ? presentationName.trim() : "CrystalPilot";
  const setPresentation = useCallback((enabled: boolean) => setPresentationSettings(previous => ({ ...previous, enabled })), []);
  const setPresentationName = useCallback((name: string) => setPresentationSettings(previous => ({ ...previous, name: name.replace(/[\r\n\t]/g, " ").slice(0, 48) })), []);
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);
  const [sysDark, setSysDark] = useState<boolean>(systemDark);
  const [palette, setPaletteState] = useState<Palette>(readStoredPalette);
  const [fontSize, setFontSizeState] = useState<FontSize>(readStoredFont);

  // follow the OS while the preference is "system"
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = (e: MediaQueryListEvent) => setSysDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const theme: Theme = preference === "system" ? (sysDark ? "dark" : "light") : preference;

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  // the tab icon follows the theme: design/CrystalPilot-logo-v1 app icon,
  // light or dark plate (ui/public/brand/; /favicon.svg is the light one
  // for the instant before React runs)
  useLayoutEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) return;
    const href = theme === "dark" ? "/brand/crystalpilot-app-dark.svg" : "/brand/crystalpilot-app-light.svg";
    if (link.getAttribute("href") !== href) link.setAttribute("href", href);
  }, [theme]);

  useLayoutEffect(() => {
    document.documentElement.dataset.palette = palette;
  }, [palette]);

  useLayoutEffect(() => {
    document.documentElement.style.setProperty(
      "--cp-scale",
      (fontSize / DEFAULT_FONT).toFixed(4),
    );
  }, [fontSize]);

  useEffect(() => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, preference);
      localStorage.setItem(PALETTE_STORAGE_KEY, palette);
      localStorage.setItem(FONT_SIZE_STORAGE_KEY, String(fontSize));
      localStorage.setItem(PRESENTATION_STORAGE_KEY, JSON.stringify(presentationSettings));
    } catch {
      /* storage unavailable */
    }
  }, [preference, palette, fontSize, presentationSettings]);

  const setPreference = useCallback((p: ThemePreference) => setPreferenceState(p), []);
  const setPalette = useCallback((p: Palette) => setPaletteState(p), []);
  const setFontSize = useCallback((n: FontSize) => setFontSizeState(n), []);
  const toggle = useCallback(() => {
    setPreferenceState(theme === "dark" ? "light" : "dark");
  }, [theme]);

  const value = useMemo(
    () => ({
      theme,
      preference,
      setPreference,
      toggle,
      palette,
      setPalette,
      fontSize,
      setFontSize,
      presentation, setPresentation, presentationName, setPresentationName, brandName,
    }),
    [theme, preference, setPreference, toggle, palette, setPalette, fontSize, setFontSize, presentation, setPresentation, presentationName, setPresentationName, brandName],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
