from pathlib import Path
import json
import os
import zipfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
PNG = ROOT / "png"
DESKTOP = ROOT / "desktop"
DESKTOP.mkdir(exist_ok=True)

# Derive all raster sizes from the same supersampled vector rendering.
for name in (
    "crystalpilot-app-light", "crystalpilot-app-dark",
    "crystalpilot-app-light-square", "crystalpilot-app-dark-square",
    "crystalpilot-symbol", "crystalpilot-monochrome",
):
    master = Image.open(PNG / f"{name}-2048.png").convert("RGBA")
    sizes = (1024,) if "square" in name else (1024, 512, 256, 128, 64, 48, 32, 24, 16)
    for size in sizes:
        resized = master.resize((size, size), Image.Resampling.LANCZOS)
        if "square" in name:
            resized = resized.convert("RGB")
        resized.save(PNG / f"{name}-{size}.png", optimize=True)
    if "square" in name:
        master.convert("RGB").save(PNG / f"{name}-2048.png", optimize=True)

for theme in ("light", "dark"):
    icon = Image.open(PNG / f"crystalpilot-app-{theme}-1024.png")
    icon.save(DESKTOP / f"CrystalPilot-{theme}.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    # macOS dock icons use a smaller canvas footprint than a mobile app icon.
    mac_icon = Image.new("RGBA", (1024, 1024))
    mac_icon.alpha_composite(icon.resize((864, 864), Image.Resampling.LANCZOS), (80, 80))
    mac_icon.save(DESKTOP / f"CrystalPilot-{theme}.icns")

# A transparent favicon keeps the letter legible at the browser's smallest size.
Image.open(PNG / "crystalpilot-symbol-1024.png").save(
    DESKTOP / "favicon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64)]
)

# The preview uses an installed open font; no font files are included in delivery.
font_source = Path(os.environ.get("INTER_FONT_PATH", ROOT.parents[1] / "ui/node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2"))
if not font_source.is_file():
    raise FileNotFoundError("Inter font not found. Install ui dependencies with npm ci, or set INTER_FONT_PATH to inter-latin-wght-normal.woff2.")
font_paths = {}
for weight in (400, 600):
    font = instantiateVariableFont(TTFont(font_source), {"wght": weight}, inplace=False)
    font.flavor = None
    font_path = ROOT / "source" / f"preview-font-{weight}.ttf"
    font.save(font_path)
    font_paths[weight] = font_path

S = 2
board = Image.new("RGBA", (1120 * S, 750 * S), "#f5f6f9")

def put_icon(name, x, y, size, shadow=False):
    icon = Image.open(PNG / f"{name}-2048.png").resize((size * S, size * S), Image.Resampling.LANCZOS)
    if shadow:
        shade = Image.new("RGBA", board.size)
        mask = Image.new("L", board.size)
        mask.paste(icon.getchannel("A").point(lambda value: round(value * .10)), (x * S, (y + 12) * S))
        mask = mask.filter(ImageFilter.GaussianBlur(16 * S))
        shade.paste("#29344b", (0, 0, *board.size), mask)
        board.alpha_composite(shade)
    board.alpha_composite(icon, (x * S, y * S))

draw = ImageDraw.Draw(board)

def label(text, x, y, size=14, weight=400, color="#858c9b", anchor="la"):
    draw.text((x * S, y * S), text, fill=color, font=ImageFont.truetype(str(font_paths[weight]), size * S), anchor=anchor)

label("CrystalPilot", 112, 67, 38, 600, "#26304a")
label("APP ICON  /  01", 1008, 86, 11, 400, "#9298a5", "ra")
put_icon("crystalpilot-app-light", 104, 165, 448, shadow=True)
put_icon("crystalpilot-app-dark", 704, 230, 264, shadow=True)
draw = ImageDraw.Draw(board)
label("Light", 328, 641, 13, anchor="ma")
label("Dark", 836, 514, 13, anchor="ma")

# The lower row previews the transparent mark at common interface sizes.
for size, x in ((64, 696), (48, 787), (32, 862), (24, 921), (16, 972)):
    put_icon("crystalpilot-symbol", x, 642 - size, size)
draw = ImageDraw.Draw(board)
label("64", 728, 661, 10, anchor="ma")
label("48", 811, 661, 10, anchor="ma")
label("32", 878, 661, 10, anchor="ma")
label("24", 933, 661, 10, anchor="ma")
label("16", 980, 661, 10, anchor="ma")

board.convert("RGB").save(ROOT / "CrystalPilot-logo-preview-2x.png", optimize=True)
board.convert("RGB").resize((1120, 750), Image.Resampling.LANCZOS).save(ROOT / "CrystalPilot-logo-preview.png", optimize=True)
for font_path in font_paths.values():
    font_path.unlink()

# Focused checks: dimensions, alpha, vector syntax, and desktop archive entries.
import xml.etree.ElementTree as ET
for svg in (ROOT / "svg").glob("*.svg"):
    ET.parse(svg)
for path in PNG.glob("*.png"):
    size = int(path.stem.rsplit("-", 1)[1])
    with Image.open(path) as im:
        assert im.size == (size, size), path
        if "square" in path.stem:
            assert im.mode == "RGB", path
        else:
            assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0, path
for path in DESKTOP.glob("*.ico"):
    with Image.open(path) as im:
        assert (16, 16) in im.ico.sizes() and (32, 32) in im.ico.sizes(), path
        im.load()
for path in DESKTOP.glob("*.icns"):
    with Image.open(path) as im:
        im.load()
        assert im.size == (1024, 1024), path

package = ROOT / "CrystalPilot-logo-v1.zip"
with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
    for folder in ("svg", "png", "desktop"):
        for path in sorted((ROOT / folder).iterdir()):
            archive.write(path, Path("CrystalPilot-logo-v1") / path.relative_to(ROOT))
    for filename in (
        "README.md", ".gitignore", "CrystalPilot-logo-preview.png", "CrystalPilot-logo-preview-2x.png",
        "source/build_vectors.py", "source/render.mjs", "source/export_assets.py",
        "source/requirements.txt", "source/size-review.png",
    ):
        archive.write(ROOT / filename, Path("CrystalPilot-logo-v1") / filename)
print(json.dumps({"vectors": len(list((ROOT / "svg").glob('*.svg'))), "pngs": len(list(PNG.glob('*.png'))), "desktop_icons": len(list(DESKTOP.iterdir())), "package": str(package), "checks": "passed"}, indent=2))
