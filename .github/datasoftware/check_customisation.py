#!/usr/bin/env python3
"""Verify that the DataSoftware customisation is intact.

This is the machine-checkable form of the "what to re-check after an upstream
merge" list in DATASOFTWARE_BUILD.md. It is cheap, needs no toolchain, and runs
both in the Windows build workflow (before the ~45 minute build) and in the
upstream sync workflow (to decide whether a merge is safe to propose).

Each check states what breaks if it fails, so a future maintainer does not have
to reverse-engineer the intent.

    python3 .github/datasoftware/check_customisation.py

Exit code 0 means every invariant holds.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

APP_NAME = "DataSoftware-Remote"
UPDATE_OWNER = "PeterLinuxOSS"
UPDATE_REPO = "rustdesk"

results = []


def read(rel):
    p = ROOT / rel
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def check(name, ok, why):
    results.append((bool(ok), name, why))


# --------------------------------------------------------------------------
# 1. The customisation module and its three hooks
# --------------------------------------------------------------------------
ds = read("src/datasoftware.rs")
lib = read("src/lib.rs")
common = read("src/common.rs")

check(
    "src/datasoftware.rs exists",
    ds is not None,
    "the whole customisation lives in this file",
)
check(
    "src/lib.rs declares the module",
    lib and "pub mod datasoftware;" in lib,
    "without the module declaration nothing else compiles",
)

if common:
    # The branding hook must sit inside load_custom_client(), which is the one
    # entry point every process (core_main, the Windows service, the Flutter
    # FFI entry, the installer path) goes through.
    m = re.search(
        r"pub fn load_custom_client\(\)\s*\{(.*?)\n\}", common, re.S
    )
    check(
        "apply_builtin_config() is called from load_custom_client()",
        m and "crate::datasoftware::apply_builtin_config();" in m.group(1),
        "otherwise the client starts with RustDesk defaults; the auto-updater "
        "runs in the service process, which only goes through this function",
    )

    m = re.search(
        r"pub async fn do_check_software_update\(\).*?\n\}", common, re.S
    )
    check(
        "do_check_software_update() uses our release lookup",
        m and "crate::datasoftware::fetch_latest_release_url()" in m.group(0),
        "otherwise update checks go back to api.rustdesk.com and "
        "rustdesk/rustdesk",
    )
else:
    check("src/common.rs readable", False, "file missing")

# --------------------------------------------------------------------------
# 2. Nothing may reach the upstream update service
# --------------------------------------------------------------------------
callers = []
for p in sorted((ROOT / "src").rglob("*.rs")):
    text = p.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(text.splitlines(), 1):
        if "version_check_request" in line and not line.strip().startswith("//"):
            callers.append("%s:%d" % (p.relative_to(ROOT).as_posix(), i))
check(
    "no caller of hbb_common::version_check_request",
    not callers,
    "that function is the only way into api.rustdesk.com/version/latest"
    + (" -- found at %s" % ", ".join(callers) if callers else ""),
)

# --------------------------------------------------------------------------
# 3. The update source is our fork
# --------------------------------------------------------------------------
if ds:
    check(
        "UPDATE_OWNER is %s" % UPDATE_OWNER,
        'UPDATE_OWNER: &str = "%s"' % UPDATE_OWNER in ds,
        "updates must come from our fork only",
    )
    check(
        "UPDATE_REPO is %s" % UPDATE_REPO,
        'UPDATE_REPO: &str = "%s"' % UPDATE_REPO in ds,
        "updates must come from our fork only",
    )
    check(
        "the GitHub releases endpoint is used",
        "api.github.com/repos/{UPDATE_OWNER}/{UPDATE_REPO}/releases/latest" in ds,
        "the updater resolves the latest version through this endpoint",
    )

# --------------------------------------------------------------------------
# 4. The contract with upstream's updater
# --------------------------------------------------------------------------
updater = read("src/updater.rs")
if updater:
    check(
        "updater still builds rustdesk-<version>-<arch>.<ext> asset names",
        "rustdesk-{}-{}.{}" in updater,
        "if upstream changed the asset name, the build workflow must publish "
        "the new name instead",
    )
    check(
        "updater still derives the download URL by replacing 'tag'",
        'replace("tag", "download")' in updater,
        "fetch_latest_release_url() returns a .../releases/tag/<v> URL "
        "specifically because of this",
    )
    check(
        "updater still honours allow-auto-update",
        "OPTION_ALLOW_AUTO_UPDATE" in updater,
        "that is the option apply_builtin_config() enables",
    )
else:
    check("src/updater.rs exists", False, "the Windows auto-updater is gone")

# --------------------------------------------------------------------------
# 5. The settings maps the built-in config writes into
# --------------------------------------------------------------------------
hbb_config = read("libs/hbb_common/src/config.rs")
if hbb_config:
    for sym in ("APP_NAME", "OVERWRITE_SETTINGS", "DEFAULT_SETTINGS"):
        check(
            "hbb_common::config::%s still exists" % sym,
            "pub static ref %s" % sym in hbb_config,
            "apply_builtin_config() writes into it",
        )
    check(
        "Config::get_option still prefers OVERWRITE_SETTINGS",
        re.search(
            r"pub fn get_option\(k: &str\) -> String \{\s*get_or\(\s*&OVERWRITE_SETTINGS",
            hbb_config,
            re.S,
        )
        is not None,
        "our server settings are enforced through that precedence",
    )

if common:
    check(
        "is_custom_client() is still derived from the app name",
        re.search(
            r'pub fn is_custom_client\(\) -> bool \{\s*get_app_name\(\) != "RustDesk"',
            common,
            re.S,
        )
        is not None,
        "the rebranded app name is what puts the client into custom-client mode",
    )

# --------------------------------------------------------------------------
# 5b. The keys:: constants apply_builtin_config() uses must live where we
#     import them from.
#
#     This is a real upstream move, not a hypothetical: in 1.4.9 these
#     constants are in libs/hbb_common/src/config.rs, and on later upstream
#     versions all but OPTION_RELAY_SERVER moved to libs/base/src/config/keys.rs
#     ("Only the keys hbb_common itself references" stayed behind). Merging such
#     a release without adjusting the `use` in src/datasoftware.rs produces a
#     compile error, so catch it here in a second rather than 40 minutes into
#     the Windows build.
# --------------------------------------------------------------------------
if ds:
    used = sorted(set(re.findall(r"keys::(OPTION_[A-Z0-9_]+)", ds)))
    if re.search(r"use\s+base::config::keys", ds) or re.search(
        r"use\s+base::\{[^}]*\bconfig::\{[^}]*\bkeys\b", ds, re.S
    ):
        crate, src_root = "base", ROOT / "libs" / "base" / "src"
    else:
        crate, src_root = "hbb_common", ROOT / "libs" / "hbb_common" / "src"

    if not src_root.is_dir():
        check(
            "the crate providing keys:: exists (%s)" % crate,
            False,
            "src/datasoftware.rs imports keys from %s" % crate,
        )
    else:
        blob = "\n".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in src_root.rglob("*.rs")
        )
        missing = [c for c in used if ("pub const %s:" % c) not in blob]
        elsewhere = {}
        for c in missing:
            for other in (ROOT / "libs").rglob("*.rs"):
                if ("pub const %s:" % c) in other.read_text(
                    encoding="utf-8", errors="replace"
                ):
                    elsewhere[c] = other.relative_to(ROOT).as_posix()
                    break
        hint = ""
        if elsewhere:
            hint = "; now defined in " + ", ".join(
                "%s (%s)" % (k, v) for k, v in elsewhere.items()
            )
        check(
            "all keys::OPTION_* used by apply_builtin_config() exist in %s" % crate,
            not missing,
            "src/datasoftware.rs imports keys from %s but %s is not defined "
            "there%s -- update the `use` statement in src/datasoftware.rs"
            % (crate, ", ".join(missing) if missing else "", hint),
        )

# --------------------------------------------------------------------------
# 5c. The submodule working tree must match the pinned commit, otherwise the
#     checks above inspect the wrong hbb_common and pass for the wrong reason.
# --------------------------------------------------------------------------
import subprocess  # noqa: E402

try:
    out = subprocess.run(
        ["git", "submodule", "status", "libs/hbb_common"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    # A leading '+' means the checked-out commit differs from the pinned one.
    check(
        "libs/hbb_common is checked out at the pinned commit",
        out and not out.startswith("+"),
        "run `git submodule update --init --recursive`; otherwise these checks "
        "inspect a stale hbb_common (git submodule status: %r)" % out,
    )
except Exception as e:  # pragma: no cover
    check("libs/hbb_common submodule state readable", False, str(e))

# --------------------------------------------------------------------------
# 6. The app name must stay shell-safe
# --------------------------------------------------------------------------
if ds:
    m = re.search(r'pub const APP_NAME: &str = "([^"]*)";', ds)
    name = m.group(1) if m else None
    check("APP_NAME is defined", name is not None, "it drives all the branding")
    if name:
        check(
            "APP_NAME contains no space",
            " " not in name,
            "src/platform/windows.rs interpolates it unquoted into "
            "sc/taskkill commands and res/msi/preprocess.py runs "
            "'<dist>/<app name>.exe' through cmd.exe unquoted",
        )
        check(
            "APP_NAME is alphanumeric or hyphen",
            re.fullmatch(r"[A-Za-z0-9-]+", name) is not None,
            "upstream states this constraint in src/lang.rs",
        )
        check(
            "APP_NAME matches the build workflow",
            ("APP_NAME: %s" % name)
            in (read(".github/workflows/datasoftware-windows.yml") or ""),
            "the MSI installs '<app name>.exe' and the runtime looks for "
            "exactly that file name",
        )

# --------------------------------------------------------------------------
# 7. Version consistency (the auto-update loop guard)
# --------------------------------------------------------------------------
cargo_toml = read("Cargo.toml")
cargo_lock = read("Cargo.lock")
if cargo_toml and cargo_lock:
    m = re.search(r'^version = "([^"]*)"', cargo_toml, re.M)
    toml_v = m.group(1) if m else None
    m = re.search(
        r'\[\[package\]\]\r?\nname = "rustdesk"\r?\nversion = "([^"]*)"', cargo_lock
    )
    lock_v = m.group(1) if m else None
    check(
        "Cargo.toml and Cargo.lock agree on the version",
        toml_v is not None and toml_v == lock_v,
        "build.py runs `cargo build --locked`, which fails when they differ "
        "(Cargo.toml=%s, Cargo.lock=%s)" % (toml_v, lock_v),
    )
    check(
        "the version has a numeric build suffix",
        toml_v is not None and re.fullmatch(r"\d+\.\d+\.\d+(-\d+)?", toml_v),
        "get_version_number() only reads a numeric -N suffix; anything else "
        "compares equal to the base version and would never be offered "
        "(version=%s)" % toml_v,
    )

# --------------------------------------------------------------------------
# 8. User-visible Windows branding
# --------------------------------------------------------------------------
rc = read("flutter/windows/runner/Runner.rc")
if rc:
    for key, value in (
        ("ProductName", "DataSoftware Remote"),
        ("CompanyName", "DataSoftware"),
        ("FileDescription", "DataSoftware Remote"),
    ):
        check(
            "Runner.rc %s is branded" % key,
            'VALUE "%s", "%s"' % (key, value) in rc,
            "this is what Explorer shows under Properties -> Details",
        )

# --------------------------------------------------------------------------
# 9. Enforced client behaviour
# --------------------------------------------------------------------------
if ds:
    # Match the insert() call, not just the string: the same literal also
    # appears in a doc comment and in the unit test, so a plain substring
    # search would still pass after the real setting was changed.
    check(
        "the permanent password is enforced",
        re.search(
            r"OPTION_VERIFICATION_METHOD\.to_owned\(\)\s*,\s*"
            r'"use-permanent-password"',
            ds,
            re.S,
        )
        is not None,
        "with one-time passwords an unattended machine cannot be reached "
        "unless somebody is sitting in front of it",
    )
    check(
        "the Discovered tab is hidden",
        re.search(
            r'OPTION_DISABLE_DISCOVERY_PANEL\.to_owned\(\)\s*,\s*"Y"', ds, re.S
        )
        is not None,
        "LAN discovery is switched off for this deployment",
    )

# --------------------------------------------------------------------------
# 10. The Dart half: first-run permanent password
# --------------------------------------------------------------------------
dart = read("flutter/lib/datasoftware.dart")
home = read("flutter/lib/desktop/pages/desktop_home_page.dart")
check(
    "flutter/lib/datasoftware.dart exists",
    dart is not None,
    "it generates and displays the per-machine permanent password",
)
check(
    "the home page calls ensureInitialPermanentPassword()",
    home and "ensureInitialPermanentPassword()" in home,
    "without the hook no password is ever generated or shown, and the "
    "machine ends up unreachable",
)
check(
    "the home page imports the DataSoftware module",
    home and "package:flutter_hbb/datasoftware.dart" in home,
    "the hook would not compile otherwise",
)
if dart:
    # Anchor on the assignment: the same text appears in the comment above it,
    # so a plain substring search passes even after the real call is changed.
    check(
        "the password uses a cryptographic RNG",
        re.search(r"=\s*Random\.secure\(\)", dart) is not None,
        "the default Random() is predictable and would make every generated "
        "password guessable",
    )

# --------------------------------------------------------------------------
# 11. Branding assets
# --------------------------------------------------------------------------
def png_size(rel):
    """Read a PNG's dimensions from its IHDR, without needing Pillow."""
    p = ROOT / rel
    if not p.exists():
        return None
    data = p.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


check(
    "the logo source is committed",
    (ROOT / ".github/datasoftware/logo-source.png").exists(),
    "generate_icons.py regenerates every icon from it",
)
check(
    "flutter/assets/icon.png is present",
    png_size("flutter/assets/icon.png") is not None,
    "it is both the in-app logo and, via src/tray.rs, the Windows tray icon; "
    "upstream does not ship this file, so a merge that removes it silently "
    "reverts the tray to the RustDesk logo",
)
for rel, expected in (
    ("res/32x32.png", (32, 32)),
    ("res/64x64.png", (64, 64)),
    ("res/128x128.png", (128, 128)),
):
    check(
        "%s is %dx%d" % (rel, expected[0], expected[1]),
        png_size(rel) == expected,
        "packaging expects this exact size",
    )

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
failed = [r for r in results if not r[0]]
for ok, name, why in results:
    print("%s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("       why it matters: %s" % why)

print("\n%d checks, %d failed" % (len(results), len(failed)))
if failed:
    print("\nThe DataSoftware customisation is broken. See DATASOFTWARE_BUILD.md")
    sys.exit(1)
print("The DataSoftware customisation is intact.")
