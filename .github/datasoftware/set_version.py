#!/usr/bin/env python3
"""Set the DataSoftware Remote build version.

The version the client reports must equal the GitHub release tag, otherwise the
auto-updater downloads the same release on every check (see DATASOFTWARE_BUILD.md).

`crate::VERSION` is generated from the `version` field of the root Cargo.toml by
hbb_common's `gen_version()`, so that field is the source of truth. Cargo.lock
records the same version for the root package and the build uses
`cargo build --locked`, so both files have to move together.

Usage:
    python3 .github/datasoftware/set_version.py 1.4.9-1
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Upstream's get_version_number() reads "X.Y.Z" plus an optional numeric "-N"
# build suffix; anything else silently compares as the bare X.Y.Z version.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-\d+)?$")


def read(path: Path) -> str:
    # newline="" keeps CRLF intact, so the script never rewrites line endings.
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def set_cargo_toml(version: str) -> None:
    path = ROOT / "Cargo.toml"
    text = read(path)
    # No `$` anchor: a Windows checkout has CRLF line endings, and the stray
    # \r would sit between the closing quote and the end of the line.
    new_text, n = re.subn(
        r'^(version = )"[^"]*"',
        lambda m: '%s"%s"' % (m.group(1), version),
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise SystemExit("Could not find the package version in %s" % path)
    write(path, new_text)
    print('Cargo.toml: version = "%s"' % version)


def set_cargo_lock(version: str) -> None:
    path = ROOT / "Cargo.lock"
    text = read(path)
    new_text, n = re.subn(
        r'(\[\[package\]\]\r?\nname = "rustdesk"\r?\nversion = )"[^"]*"',
        lambda m: '%s"%s"' % (m.group(1), version),
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit("Could not find the rustdesk package entry in %s" % path)
    write(path, new_text)
    print('Cargo.lock: rustdesk version = "%s"' % version)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: set_version.py <version>, e.g. 1.4.9-1")
    version = sys.argv[1].strip()
    if not VERSION_RE.match(version):
        raise SystemExit(
            "Version %r must look like 1.4.9 or 1.4.9-1; a non-numeric suffix "
            "would not compare as newer and the update would never be offered."
            % version
        )
    set_cargo_toml(version)
    set_cargo_lock(version)


if __name__ == "__main__":
    main()
