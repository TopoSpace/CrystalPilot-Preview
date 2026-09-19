/** The CrystalPilot mark, from design/CrystalPilot-logo-v1 (the SVGs are
 * copied verbatim to ui/public/brand/). `symbol` is the transparent colour
 * mark for chrome such as the sidebar brand row; `app` is the rounded app
 * icon, light or dark plate per theme, for hero areas. Both are plain
 * images: no inline SVG, no font, nothing to hydrate. */
import { useTheme } from "../lib/theme";

export const BRAND = {
  symbol: "/brand/crystalpilot-symbol.svg",
  mono: "/brand/crystalpilot-monochrome.svg",
  appLight: "/brand/crystalpilot-app-light.svg",
  appDark: "/brand/crystalpilot-app-dark.svg",
} as const;

export function brandAppIcon(theme: "light" | "dark"): string {
  return theme === "dark" ? BRAND.appDark : BRAND.appLight;
}

export function BrandMark({
  size = 22,
  variant = "symbol",
  className = "",
}: {
  size?: number;
  variant?: "symbol" | "app";
  className?: string;
}) {
  const { theme } = useTheme();
  const src = variant === "app" ? brandAppIcon(theme) : BRAND.symbol;
  return (
    <img
      src={src}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      draggable={false}
      className={`shrink-0 select-none ${className}`.trim()}
      data-testid="brand-mark"
      data-variant={variant}
      data-theme={theme}
    />
  );
}
