"""Original CrystalPilot identity, authored as editable vector geometry."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG_DIR = ROOT / "svg"
SVG_DIR.mkdir(parents=True, exist_ok=True)

# A crystal section with an open face: a C formed by five broad planes.
SILHOUETTE = (
    "M 262 106 Q 266 103.7 270 106 L 388 174.6 Q 393 177.5 389 181.3 "
    "L 345.4 223.4 Q 342.5 226.2 339 224.2 L 269 183.8 "
    "Q 266 182.1 263 183.8 L 201.7 219.1 Q 199 220.7 199 224 "
    "L 199 306 Q 199 309.3 201.7 310.9 L 263 346.2 "
    "Q 266 347.9 269 346.2 L 339 305.8 Q 342.5 303.8 345.4 306.6 "
    "L 389 348.7 Q 393 352.5 388 355.4 L 270 424 "
    "Q 266 426.3 262 424 L 126 345.3 Q 122 343 122 338.4 "
    "L 122 191.6 Q 122 187 126 184.7 Z"
)
TILE = (
    "M 184 8 H 328 C 389 8 420 8 443 20 "
    "C 464 31 481 48 492 69 C 504 92 504 123 504 184 "
    "V 328 C 504 389 504 420 492 443 C 481 464 464 481 443 492 "
    "C 420 504 389 504 328 504 H 184 "
    "C 123 504 92 504 69 492 C 48 481 31 464 20 443 "
    "C 8 420 8 389 8 328 V 184 C 8 123 8 92 20 69 "
    "C 31 48 48 31 69 20 C 92 8 123 8 184 8 Z"
)


def icon(theme="light", rounded=True, symbol_only=False):
    dark = theme == "dark"
    bg_top, bg_bottom = ("#262d40", "#111525") if dark else ("#fdfefe", "#edf0f7")
    top_left = ("#b2d6ff", "#7499ff") if dark else ("#9fc5ff", "#6586f0")
    top_right = ("#e1efff", "#91a7ff") if dark else ("#c3e2ff", "#8b9ff7")
    side = ("#7f9dff", "#6572e8") if dark else ("#5c7be7", "#5862cc")
    base = ("#7888f4", "#5757ca") if dark else ("#5963d2", "#4242a5")
    end = ("#c1caff", "#8b98f0") if dark else ("#aabcf5", "#7c8bdc")
    tile = f'<path d="{TILE}" fill="url(#background)"/>' if rounded else '<rect width="512" height="512" fill="url(#background)"/>'
    edge = f'<path d="{TILE}" fill="none" stroke="{ "#ffffff" if dark else "#d6dce9" }" stroke-opacity="{ ".07" if dark else ".65" }" stroke-width=".65"/>' if rounded else ""
    if symbol_only:
        tile = edge = ""
    gradient_specs = [
        ("background", "0", "0", "360", "512", (bg_top, bg_bottom)),
        ("top-left", "129", "181", "261", "220", top_left),
        ("top-right", "281", "116", "353", "219", top_right),
        ("side", "121", "183", "191", "344", side),
        ("base", "158", "321", "263", "426", base),
        ("end", "376", "310", "264", "421", end),
    ]
    gradients = "\n".join(
        f'<linearGradient id="{name}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" gradientUnits="userSpaceOnUse"><stop stop-color="{colors[0]}"/><stop offset="1" stop-color="{colors[1]}"/></linearGradient>'
        for name, x1, y1, x2, y2, colors in gradient_specs
    )
    shadow = "" if symbol_only else ' filter="url(#soft-shadow)"'
    view_box = "100 80 314 354" if symbol_only else "0 0 512 512"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="{view_box}" fill="none">
  <title>CrystalPilot — crystal C, {theme}</title>
  <desc>An original open crystal section, drawn as five broad blue and indigo planes.</desc>
  <defs>
    {gradients}
    <clipPath id="crystal-clip"><path d="{SILHOUETTE}"/></clipPath>
    <filter id="soft-shadow" x="70" y="73" width="375" height="409" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="{ '#000514' if dark else '#344276' }" flood-opacity="{ '.32' if dark else '.13' }"/>
      <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="{ '#000514' if dark else '#434577' }" flood-opacity=".08"/>
    </filter>
  </defs>
  {tile}
  {edge}
  <g transform="translate(0 -9)"{shadow}>
    <path d="{SILHOUETTE}" fill="url(#side)"/>
    <g clip-path="url(#crystal-clip)">
      <path d="M 121 187 266 103 267 183 199 223 Z" fill="url(#top-left)"/>
      <path d="M 266 103 395 177 342 227 266 183 Z" fill="url(#top-right)"/>
      <path d="M 121 187 199 221 199 309 121 344 Z" fill="url(#side)"/>
      <path d="M 121 343 199 308 266 347 267 427 Z" fill="url(#base)"/>
      <path d="M 266 347 342 303 395 353 266 427 Z" fill="url(#end)"/>
      <path d="M 123 187 266 104 391 177 M 123 188 198 221 M 267 104 267 182" stroke="#fff" stroke-opacity=".30" stroke-width=".9"/>
      <path d="M 199 310 266 348 342 305" stroke="#e0e9ff" stroke-opacity=".32" stroke-width=".85"/>
    </g>
  </g>
</svg>
'''
    return "\n".join(line.rstrip() for line in svg.splitlines()) + "\n"


for theme in ("light", "dark"):
    (SVG_DIR / f"crystalpilot-app-{theme}.svg").write_text(icon(theme), encoding="utf-8")
    (SVG_DIR / f"crystalpilot-app-{theme}-square.svg").write_text(icon(theme, rounded=False), encoding="utf-8")

(SVG_DIR / "crystalpilot-symbol.svg").write_text(icon(symbol_only=True), encoding="utf-8")
(SVG_DIR / "crystalpilot-monochrome.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="100 80 314 354"><title>CrystalPilot — monochrome</title><path transform="translate(0 -9)" d="{SILHOUETTE}" fill="currentColor"/></svg>\n', encoding="utf-8"
)
print(f"Wrote six vector masters to {SVG_DIR}")
