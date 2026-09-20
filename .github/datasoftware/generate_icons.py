#!/usr/bin/env python3
"""Regenerate the DataSoftware application icons from one source image.

    python3 .github/datasoftware/generate_icons.py [source.png]

The source defaults to .github/datasoftware/logo-source.png, which is the
DataSoftware app icon from datasoftware.sk (512x512, transparent rounded
corners). Needs Pillow; it is not part of the build, only run when the logo
changes, and the generated files are committed.

Which file ends up where matters, because RustDesk reads them from four
different places:

  flutter/assets/icon.png
      In-app logo (`loadIcon()` prefers assets/icon.png over assets/icon.svg)
      AND the Windows tray icon: src/tray.rs::load_icon_from_asset() reads
      data\\flutter_assets\\assets\\icon.png next to the executable and only
      falls back to res/tray-icon.ico when it is missing.
  flutter/windows/runner/resources/app_icon.ico
      The executable icon, referenced by flutter/windows/runner/Runner.rc.
  res/icon.ico
      Copied by res/msi/preprocess.py into the MSI, so it is the installer and
      Add/Remove Programs icon.
  res/tray-icon.ico
      Tray fallback, compiled into the binary by src/tray.rs.

The remaining res/*.png sizes are Linux/macOS packaging assets. They are
regenerated for consistency even though this fork only ships Windows.
"""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow is required: pip install Pillow")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path(__file__).resolve().parent / "logo-source.png"

# Windows picks the best match from an .ico, so give it the usual ladder.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
TRAY_ICO_SIZES = [16, 24, 32]

PNG_TARGETS = [
    ("flutter/assets/icon.png", 512),
    ("res/icon.png", 512),
    ("res/128x128@2x.png", 256),
    ("res/128x128.png", 128),
    ("res/64x64.png", 64),
    ("res/32x32.png", 32),
]

ICO_TARGETS = [
    ("flutter/windows/runner/resources/app_icon.ico", ICO_SIZES),
    ("res/icon.ico", ICO_SIZES),
    ("res/tray-icon.ico", TRAY_ICO_SIZES),
]


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        raise SystemExit("Source image not found: %s" % source)

    src = Image.open(source).convert("RGBA")
    if src.width != src.height:
        raise SystemExit(
            "Source must be square, got %dx%d" % (src.width, src.height)
        )
    print("source: %s (%dx%d)" % (source, src.width, src.height))

    for rel, size in PNG_TARGETS:
        out = ROOT / rel
        if size > src.width:
            print("  note: upscaling to %d from a %dpx source" % (size, src.width))
        img = src.resize((size, size), Image.LANCZOS)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG", optimize=True)
        print("  %-50s %dx%d" % (rel, size, size))

    for rel, sizes in ICO_TARGETS:
        out = ROOT / rel
        usable = [s for s in sizes if s <= src.width]
        # Pillow builds every requested size from the image it is given, so
        # hand it the full-resolution source and let it downscale.
        out.parent.mkdir(parents=True, exist_ok=True)
        src.save(out, "ICO", sizes=[(s, s) for s in usable])
        print("  %-50s %s" % (rel, ",".join(str(s) for s in usable)))

    print("\nDone. Commit the regenerated files.")


if __name__ == "__main__":
    main()
