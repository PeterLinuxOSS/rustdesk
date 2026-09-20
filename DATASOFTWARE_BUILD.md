# DataSoftware Remote — build and maintenance

`DataSoftware Remote` is a customised build of the RustDesk OSS client for
DataSoftware's self-hosted RustDesk infrastructure. It is a normal RustDesk
client: no RustDesk Server Pro features are used and no paid components are
required.

This document is the maintenance contract for the fork. It contains no secrets.

- Branch: `datasoftware-custom-client`
- Base: upstream tag `1.4.9`
- Upstream: <https://github.com/rustdesk/rustdesk>
- Fork: <https://github.com/PeterLinuxOSS/rustdesk>

---

## 1. What is customised

The customisation is deliberately tiny and kept in one place. Everything else
in the tree is untouched upstream code.

| File | Purpose |
| --- | --- |
| `src/datasoftware.rs` | **All** DataSoftware configuration and the update-source lookup. New file. |
| `src/lib.rs` | One line: `pub mod datasoftware;` |
| `src/common.rs` | Two marked hooks (see below). |
| `flutter/lib/desktop/pages/desktop_setting_page.dart` | About dialog: website link and copyright line. |
| `flutter/windows/runner/Runner.rc` | Windows executable metadata. |
| `Cargo.toml`, `Cargo.lock` | Build version (see §5). |
| `.github/workflows/datasoftware-windows.yml` | Windows x86_64 build and release. New file. |
| `.github/datasoftware/set_version.py` | Keeps the build version and the release tag in sync. New file. |

The hooks in `src/common.rs` are wrapped in
`// >>> DataSoftware ... <<<` comment markers so they are easy to find in a
merge conflict.

### Branding

- Application name: **DataSoftware-Remote**
- Company / website: **DataSoftware**, <https://datasoftware.sk>

> **The app name must not contain a space.** It is not just a label: upstream
> interpolates it unquoted into Windows shell commands — `sc create {app_name}`,
> `sc stop/delete/start {app_name}` and `taskkill /F /IM {app_name}.exe`, 17
> places in `src/platform/windows.rs` — and `res/msi/preprocess.py` runs
> `<dist>/<app name>.exe` through cmd.exe without quoting the path. A space
> splits the service name and breaks installation and the MSI build. Upstream
> documents the same constraint in `src/lang.rs`: *"app_name only contains
> alphanumeric and hyphen"*. `src/datasoftware.rs` has a unit test enforcing it,
> and the build workflow checks that its `APP_NAME` matches the Rust constant.
>
> The spaced form **DataSoftware Remote** is therefore used only where it is
> purely cosmetic and safe: the Windows executable metadata
> (`ProductName`, `FileDescription`) in `flutter/windows/runner/Runner.rc`, which
> is what Explorer shows under Properties → Details.

The name is set once, via `config::APP_NAME`. Upstream derives a lot from that
single value, so most of the branding follows automatically:

- window title (`flutter/windows/runner/main.cpp` reads it from the DLL through
  `get_rustdesk_app_name`),
- install directory `C:\Program Files\DataSoftware-Remote`, installed
  executable `DataSoftware-Remote.exe`, Windows service name and the
  Add/Remove Programs entry (`src/platform/windows.rs`),
- configuration directory `%APPDATA%\DataSoftware-Remote`,
- every translated string: `src/lang.rs` replaces `RustDesk` with the app name
  for custom clients, so e.g. `About RustDesk` renders as
  `About DataSoftware-Remote`,
- `is_custom_client()`, which upstream defines as
  `get_app_name() != "RustDesk"`.

MSI branding is passed to `res/msi/preprocess.py` as build arguments
(`--app-name`, `-m`), not patched into the source.

**Deliberately left as `rustdesk`** — changing these would break the build, the
updater or Windows compatibility:

- the Cargo package name, the `rustdesk.exe` build output and the
  `rustdesk-*` release asset names (see §4),
- `InternalName` / `OriginalFilename` in `Runner.rc`, which describe the actual
  built file,
- DLL, printer-driver, virtual-display and service component names,
  `RuntimeBroker_rustdesk.exe`, the `rustdesk://` URI scheme and the IPC
  protocol identifiers.

### Server configuration

| Setting | Value |
| --- | --- |
| ID / rendezvous server | `api.datasoftware.sk` |
| API server | `https://remote.datasoftware.sk` |
| Relay server | empty — automatic |
| Public key | `7yMWvosWrAbR2iUFsvbyL0YrMx9P839UfShu+bdwMGg=` |
| `allow-auto-update` | `Y` |

Only the **public** server key is shipped. The RustDesk server private key must
never be committed to this repository.

---

## 2. How the server configuration is implemented

`src/datasoftware.rs::apply_builtin_config()` is called from
`src/common.rs::load_custom_client()`.

Why there: `load_custom_client()` is the single function every process entry
point calls — `core_main()`, the Windows service (`src/service.rs`), the Flutter
FFI entry (`src/flutter_ffi.rs`) and the Windows installer path
(`src/platform/windows.rs`). Hooking the function instead of its call sites
means no process can start without the configuration. The Windows auto-updater
runs in the **service** process, so patching only `core_main()` would silently
break updates.

What it does:

- sets `config::APP_NAME`,
- puts the ID server, API server, public key and the (empty) relay into
  `config::OVERWRITE_SETTINGS`,
- puts `allow-auto-update = Y` into `config::DEFAULT_SETTINGS`.

These are exactly the maps upstream fills from a signed custom client bundle,
so the resulting behaviour is upstream behaviour.

`OVERWRITE_SETTINGS` values are enforced: `Config::get_option()` prefers them
over the user's configuration file, and `Config::set_option()` refuses to
persist a different value. `DEFAULT_SETTINGS` values are only defaults, so an
administrator can still turn auto-update off on a single machine.

Nothing is written to the user's configuration file, so a fresh install is
configured out of the box and unrelated user preferences are never overwritten
on startup.

### Why not upstream's `custom.txt`

Upstream's native custom-client mechanism (`read_custom_client()`) expects a
base64 blob that is **signed with a RustDesk-owned private key** and verified
against the public key hard-coded in `src/common.rs`. We cannot produce a valid
one, so we write the same values into the same maps directly.

The signed path is still intact: if a signed `custom.txt` is ever placed next
to the executable, `load_custom_client()` reads it after our defaults and it
wins.

The filename-based mechanism (`src/custom_server.rs`, the
`rustdesk-host=...,key=...` executable name, and the reversed-base64 config
string) also still works and takes priority via `EXE_RENDEZVOUS_SERVER`. It is
not used for this build.

---

## 3. How the updater was redirected

### Upstream flow

1. `src/rendezvous_mediator.rs` starts `updater::start_auto_update()` on
   Windows when the client is installed and running as the server/service.
2. `src/updater.rs::check_update()` honours `allow-auto-update` and calls
   `common::do_check_software_update()`.
3. `do_check_software_update()` POSTs to `https://api.rustdesk.com/version/latest`
   (via `hbb_common::version_check_request`), which answers with a
   `https://github.com/rustdesk/rustdesk/releases/tag/<version>` URL, and stores
   it in `common::SOFTWARE_UPDATE_URL`.
4. `updater.rs` turns that into a download URL with
   `update_url.replace("tag", "download")` and appends
   `/rustdesk-<version>-<arch>.<exe|msi>`.
5. It downloads the asset and runs it with `--update`.

### What we changed

**Only step 3.** `do_check_software_update()` now calls
`datasoftware::fetch_latest_release_url()`, which does a plain
`GET https://api.github.com/repos/PeterLinuxOSS/rustdesk/releases/latest`
and returns
`https://github.com/PeterLinuxOSS/rustdesk/releases/tag/<tag_name>`.

Steps 1, 2, 4 and 5 are untouched upstream code, which is why the release asset
names must keep the upstream `rustdesk-*` pattern.

There is **no fallback** to `rustdesk/rustdesk` or to `api.rustdesk.com`: if the
GitHub lookup fails, the check simply fails and is retried later.

Side effects, both intentional:

- `hbb_common::version_check_request()` now has no callers in this tree, so the
  client no longer reports a device fingerprint to `api.rustdesk.com`.
- `libs/hbb_common` is an unmodified upstream submodule. The redirect lives
  entirely in the main repository, so the submodule never needs forking.

### Other `rustdesk/rustdesk` references

A repository-wide search still finds `rustdesk/rustdesk`, but none of the
remaining hits are part of the update mechanism:

- source comments linking to upstream issues, discussions and commits,
- `.github/workflows/fdroid.yml` (Android F-Droid metadata, not built here),
- `flutter/lib/desktop/pages/desktop_home_page.dart::buildHelpCards()`, which
  links to `rustdesk.com/download` and to an upstream changelog. That whole
  branch is guarded by `!bind.isCustomClient()` and therefore never renders in
  this client.

Re-run the check after any upstream merge:

```bash
grep -rn "rustdesk/rustdesk\|api.rustdesk.com" src/ | grep -v "^src/[a-z_/]*\.rs:[0-9]*: *//"
```

---

## 4. Release assets

`src/updater.rs` builds the download file name itself:

```
rustdesk-<tag>-<arch>.exe      # arch is x86_64 or aarch64
rustdesk-<tag>-<arch>.msi
```

So the asset names **must** keep the `rustdesk-` prefix even though the
installed application is called DataSoftware-Remote. The build workflow
produces exactly these names; nothing was renamed, and the updater and the
workflow agree by construction.

Two things follow from upstream's code:

- `update_msi = is_msi_installed() && !is_custom_client()`, and this is a custom
  client, so **the auto-updater always downloads the `.exe`**, even on machines
  installed from the MSI. The MSI is there for GPO/manual deployment.
- The release must be a **full release, not a pre-release**: the updater uses
  GitHub's `/releases/latest`, which skips drafts and pre-releases. The
  workflow already publishes with `prerelease: false`.

---

## 5. Versioning — important

`crate::VERSION` is generated from the `version` field of `Cargo.toml`
(`hbb_common::gen_version()` writes `src/version.rs`). The updater compares the
release tag against `crate::VERSION`.

**If the built client reports a lower version than its own release tag, it will
re-download and re-install the same release on every check, forever.**

Therefore the release tag and the `Cargo.toml` version must be identical. The
workflow enforces this: on a tag push it runs
`.github/datasoftware/set_version.py "$TAG"`, which updates `Cargo.toml` **and**
`Cargo.lock` (the build uses `cargo build --locked`).

Use tags of the form `1.4.9-1`, `1.4.9-2`, … Upstream's `get_version_number()`
reads a trailing `-N` as a numeric build suffix, so `1.4.9-1` compares as newer
than the `1.4.9` base. A non-numeric suffix such as `1.4.9-ds1` parses as plain
`1.4.9` and would never be offered as an update; `set_version.py` rejects it.

The tag must also not contain the substring `tag`, because upstream builds the
download URL with `update_url.replace("tag", "download")`.
`fetch_latest_release_url()` checks this at runtime.

---

## 6. How to build

### GitHub Actions (the supported way)

Workflow: `.github/workflows/datasoftware-windows.yml`, target Windows x86_64.

It reuses upstream's own reusable workflows for the prerequisites
(`.github/workflows/bridge.yml` and
`.github/workflows/third-party-RustDeskTempTopMostWindow.yml`) and mirrors the
Windows x86_64 steps of upstream's `.github/workflows/flutter-build.yml`.

Triggers:

- **manual** (`workflow_dispatch`) — optional `version`, and
  `publish-release` to also create the GitHub release,
- **tag push** matching `1.4.9` or `1.4.9-1` — builds and publishes the release.

Artifacts:

| Name | Contents |
| --- | --- |
| `rustdesk-<version>-x86_64.exe` | portable / self-extracting installer |
| `rustdesk-<version>-x86_64.msi` | Windows installer |
| `datasoftware-remote-unsigned-windows-x86_64` | the unpacked build directory |

Code signing is not configured. Upstream's signing steps depend on
`secrets.SIGN_BASE_URL` / `secrets.SIGN_SECRET_KEY` and were left out.
Unsigned binaries will show a SmartScreen warning.

### Locally (Windows)

Requires Rust 1.75, Flutter 3.24.5, LLVM 15, vcpkg and Python 3. Follow
upstream's build instructions, then:

```bash
python3 .github/datasoftware/set_version.py 1.4.9-1
python3 build.py --portable --flutter --skip-portable-pack --hwcodec --vram
```

---

## 7. How to publish a release

1. Make sure `datasoftware-custom-client` is up to date and builds.
2. Pick the next build number, e.g. `1.4.9-2`.
3. Commit the version bump (optional — the workflow sets it anyway):
   ```bash
   python3 .github/datasoftware/set_version.py 1.4.9-2
   git commit -am "DataSoftware Remote 1.4.9-2"
   ```
4. Tag and push:
   ```bash
   git tag 1.4.9-2
   git push origin datasoftware-custom-client 1.4.9-2
   ```
5. The workflow builds and publishes the release with both assets.
6. Verify the release is **not** marked as a pre-release and that both
   `rustdesk-1.4.9-2-x86_64.exe` and `.msi` are attached.

Existing clients pick it up within a day (first check 30 s after start, then
every 24 h, skipped while a session is active).

---

## 8. How to merge a new upstream RustDesk release

```bash
git remote add upstream https://github.com/rustdesk/rustdesk.git   # once
git fetch upstream --tags
git checkout datasoftware-custom-client
git merge 1.5.0            # or whichever tag you are moving to
git submodule update --init --recursive
```

Then check, in this order:

1. **`src/common.rs::do_check_software_update()`** — the most fragile hook. If
   upstream changed how the latest version is discovered, or the shape of the
   URL it stores in `SOFTWARE_UPDATE_URL`, adapt the hook. The contract our code
   must satisfy is: return `https://github.com/<owner>/<repo>/releases/tag/<version>`.
2. **`src/common.rs::load_custom_client()`** — confirm
   `apply_builtin_config()` is still called, and that it is still the single
   entry point used by every process.
3. **`src/updater.rs`** — confirm the asset name pattern is still
   `rustdesk-<version>-<arch>.<exe|msi>` and that
   `update_url.replace("tag", "download")` is still how the download URL is
   built. If the pattern changed, change the workflow to match.
4. **`hbb_common::config` keys** — `apply_builtin_config()` uses
   `keys::OPTION_*` constants; a rename shows up as a compile error, a change in
   which settings map a key belongs to does not. In 1.4.9 these constants live
   in `libs/hbb_common/src/config.rs`; on later upstream versions they moved to
   `libs/base/src/config/keys.rs`, so the `use` statement may need adjusting.
5. **`config::APP_NAME` / `is_custom_client()`** — if upstream stops deriving
   custom-client behaviour from the app name, revisit the branding.
6. **`res/msi/preprocess.py`** — confirm `--app-name` and `-m` still exist and
   that the main executable is still expected as `<app name>.exe`.
7. **`flutter/windows/runner/Runner.rc`** and the About dialog strings —
   re-apply if upstream rewrote them.
8. **`.github/workflows/datasoftware-windows.yml`** — re-sync the `env:` block
   (`FLUTTER_VERSION`, `SCITER_RUST_VERSION`, `LLVM_VERSION`, `VCPKG_COMMIT_ID`)
   and the build steps with upstream's `flutter-build.yml`.

The workflow runs cheap guard rails before the long build: formatting of
`src/datasoftware.rs`, the presence of all three hooks, and a check that no
update path still points at `rustdesk/rustdesk` or `api.rustdesk.com`. It also
fails the build if the produced executable does not report the expected
branding and version.

---

## 9. Verifying a build on Windows

After installing the produced `.exe` or `.msi`:

1. The window title, Start menu entry and Add/Remove Programs say
   **DataSoftware-Remote**.
2. Right-click `DataSoftware-Remote.exe` → Properties → Details:
   Product name `DataSoftware Remote`, Company `DataSoftware` — the spaced
   form is intentional here; see the note in §1.
3. Settings → Network: ID server `api.datasoftware.sk`, API server
   `https://remote.datasoftware.sk`, relay empty, key ends with `+bdwMGg=`.
   These fields are enforced and cannot be changed.
4. The client gets an ID and a remote session works in both directions.
5. `%APPDATA%\DataSoftware-Remote\config\RustDesk2.toml` contains no
   `custom-rendezvous-server` entry — the value comes from the built-in
   override, not from the user's file.
6. Auto-update: with a newer release published, the service picks it up within
   24 h. To test immediately, install an older build and watch
   `%APPDATA%\DataSoftware-Remote\log\` — the update check runs 30 s after the
   service starts.
7. Confirm in the log, or with a network capture, that the client contacts
   `api.github.com/repos/PeterLinuxOSS/rustdesk` and never
   `api.rustdesk.com/version/latest`.

---

## 10. Licence

RustDesk is AGPL-3.0. This fork is a modified version of it and stays
AGPL-3.0; the corresponding source is this public repository.
