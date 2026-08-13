"""Cut the bird out of the source icon and stamp it onto colored backgrounds."""
from __future__ import annotations

import shutil
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "frontend" / "icons"
SOURCE_CANDIDATES = [
    ICONS / "_source.png",
    Path(
        r"C:\Users\james\.cursor\projects\c-Users-james-Documents-UBETRA\assets"
        r"\c__Users_james_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_image-53c334c6-0c7f-4d7f-b7aa-a8754320edec.png"
    ),
]

STYLES = {
    "violet": "#6d28d9",
    "sage": "#b6dba3",
    "midnight": "#1a1a1a",
    "ember": "#3d2416",
    "cream": "#efe6d8",
}


def _hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _is_background(r: int, g: int, b: int) -> bool:
    if min(r, g, b) >= 228:
        return True
    if g >= 145 and g >= r - 6 and g > b and (g - min(r, b)) >= 10:
        return True
    if g >= 108 and g > r and g > b and (r + g + b) / 3 >= 95 and abs(r - b) < 55:
        return True
    return False


def cutout_bird(src: Image.Image) -> Image.Image:
    img = src.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    seen = [[False] * w for _ in range(h)]
    queue: deque[tuple[int, int]] = deque()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (0, h // 2)):
        r, g, b, _a = pixels[x, y]
        if _is_background(r, g, b):
            queue.append((x, y))
            seen[y][x] = True
    while queue:
        x, y = queue.popleft()
        pixels[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h or seen[ny][nx]:
                continue
            r, g, b, a = pixels[nx, ny]
            if a == 0 or not _is_background(r, g, b):
                seen[ny][nx] = True
                continue
            seen[ny][nx] = True
            queue.append((nx, ny))
    # Enclosed mint pockets (between body and branch) are not reachable from the corners.
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a and _is_background(r, g, b):
                pixels[x, y] = (0, 0, 0, 0)
    # Eat remaining mint fringe that touches transparency.
    for _ in range(2):
        fringe = []
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if a == 0 or not _is_background(r, g, b):
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and pixels[nx, ny][3] == 0:
                        fringe.append((x, y))
                        break
        for x, y in fringe:
            pixels[x, y] = (0, 0, 0, 0)
    bbox = img.getbbox()
    if not bbox:
        raise RuntimeError("Icon cutout produced an empty image")
    return img.crop(bbox)


def fit_on_canvas(bird: Image.Image, size: int, padding_ratio: float) -> Image.Image:
    inner = max(8, int(size * (1 - 2 * padding_ratio)))
    bw, bh = bird.size
    scale = min(inner / bw, inner / bh)
    new_size = (max(1, int(bw * scale)), max(1, int(bh * scale)))
    scaled = bird.resize(new_size, Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer.paste(scaled, ((size - new_size[0]) // 2, (size - new_size[1]) // 2), scaled)
    return layer.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=2))


def stamp(bird_layer: Image.Image, hex_color: str) -> Image.Image:
    bg = Image.new("RGBA", bird_layer.size, (*_hex_rgb(hex_color), 255))
    return Image.alpha_composite(bg, bird_layer).convert("RGB")


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


ANDROID_RES = ROOT / "mobile" / "android-icons"
LAUNCHER_SIZES = (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192))
FOREGROUND_SIZES = (("mdpi", 108), ("hdpi", 162), ("xhdpi", 216), ("xxhdpi", 324), ("xxxhdpi", 432))
ADAPTIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
</adaptive-icon>
"""
BACKGROUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#6D28D9</color>
</resources>
"""


def write_android_launcher(bird: Image.Image) -> None:
    if ANDROID_RES.exists():
        shutil.rmtree(ANDROID_RES)
    for dens, size in LAUNCHER_SIZES:
        icon = stamp(fit_on_canvas(bird, size, 0.12), STYLES["violet"])
        save_png(icon, ANDROID_RES / f"mipmap-{dens}" / "ic_launcher.png")
        save_png(icon, ANDROID_RES / f"mipmap-{dens}" / "ic_launcher_round.png")
    for dens, size in FOREGROUND_SIZES:
        save_png(
            fit_on_canvas(bird, size, 0.22),
            ANDROID_RES / f"mipmap-{dens}" / "ic_launcher_foreground.png",
        )
    anydpi = ANDROID_RES / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    (anydpi / "ic_launcher.xml").write_text(ADAPTIVE_XML, encoding="utf-8")
    (anydpi / "ic_launcher_round.xml").write_text(ADAPTIVE_XML, encoding="utf-8")
    values = ANDROID_RES / "values"
    values.mkdir(parents=True, exist_ok=True)
    (values / "ic_launcher_background.xml").write_text(BACKGROUND_XML, encoding="utf-8")
    print(f"Wrote Android launcher icons to {ANDROID_RES}")


def main() -> None:
    src_path = next((p for p in SOURCE_CANDIDATES if p.is_file()), None)
    if src_path is None:
        raise SystemExit("Could not find the source bird icon")
    ICONS.mkdir(parents=True, exist_ok=True)
    dest_source = ICONS / "_source.png"
    if src_path.resolve() != dest_source.resolve():
        shutil.copy2(src_path, dest_source)
    bird = cutout_bird(Image.open(dest_source))
    any_layer = fit_on_canvas(bird, 512, 0.10)
    mask_layer = fit_on_canvas(bird, 512, 0.18)
    small_layer = fit_on_canvas(bird, 192, 0.10)
    for name, color in STYLES.items():
        folder = ICONS / name
        save_png(stamp(small_layer, color), folder / "icon-192.png")
        save_png(stamp(any_layer, color), folder / "icon-512.png")
        save_png(stamp(mask_layer, color), folder / "icon-512-maskable.png")
    # Default Android / legacy paths stay on violet.
    for filename in ("icon-192.png", "icon-512.png", "icon-512-maskable.png"):
        shutil.copy2(ICONS / "violet" / filename, ICONS / filename)
    write_android_launcher(bird)
    print(f"Wrote icon styles to {ICONS}")


if __name__ == "__main__":
    main()
