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
| `.github/workflows/datasoftware-upstream-sync.yml` | Weekly upstream merge proposal. New file. |
| `.github/datasoftware/set_version.py` | Keeps the build version and the release tag in sync. New file. |
| `.github/datasoftware/check_customisation.py` | Verifies the customisation is intact. New file. |
| `.github/datasoftware/merge_upstream.sh` | Performs an upstream merge safely. New file. |
| `.claude/agents/upstream-sync.md` | Claude Code agent for merges that need judgement. New file. |
| `.github/datasoftware/generate_icons.py` + `logo-source.png` | Regenerates every icon from the logo. New files. |
| `flutter/lib/datasoftware.dart` | First-run permanent password. New file. |
| `flutter/lib/desktop/pages/desktop_home_page.dart` | One hook: shows the first-run password. |
| `flutter/assets/icon.png`, `res/*.png`, `res/*.ico`, `app_icon.ico` | Branded icons. |
| `src/lang/sk.rs`, `src/lang/en.rs` | Strings for the password dialog. |
| `.gitignore` | Two `!` exceptions so the new PNGs are not ignored. |

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

### Icons

Every icon comes from the DataSoftware logo, regenerated from one source by:

```bash
python3 .github/datasoftware/generate_icons.py
```

The source is `.github/datasoftware/logo-source.png` (512x512, the app icon
from datasoftware.sk). Replace it and re-run to change the logo. RustDesk reads
icons from four unrelated places, and all four have to be updated together:

| File | Where it shows |
| --- | --- |
| `flutter/assets/icon.png` | In-app logo (`loadIcon()`) **and** the Windows tray: `src/tray.rs::load_icon_from_asset()` reads `data\flutter_assets\assets\icon.png` next to the exe and only falls back to `res/tray-icon.ico` if it is missing |
| `flutter/windows/runner/resources/app_icon.ico` | The executable, via `Runner.rc` |
| `res/icon.ico` | Copied into the MSI by `res/msi/preprocess.py`: installer and Add/Remove Programs |
| `res/tray-icon.ico` | Tray fallback, compiled in by `src/tray.rs` |

`.gitignore` has a repository-wide `*png` rule. `flutter/assets/icon.png` and
the logo source are new files in this fork, so they needed explicit `!`
exceptions — without them the branded tray icon silently never ships. The
`res/*.png` files were already tracked, so the rule never affected them.

### Client behaviour

| Setting | Value | Map |
| --- | --- | --- |
| `disable-discovery-panel` | `Y` | `OVERWRITE_LOCAL_SETTINGS` |

Enforced, so the "Discovered" (LAN discovery) tab is gone and the customer
cannot switch it back on.

**`verification-method` is deliberately left alone.** Upstream's default is
`use-both-passwords`, under which the permanent password already works
(`hbb_common::password_security::permanent_enabled()` is true for anything but
`OnlyUseTemporaryPassword`). Pinning `use-permanent-password` would not enable
anything — it would only switch off the one-time password, and that is the
only credential a machine has until the UI runs for the first time. Upstream
never generates a permanent password on its own, so on a silent MSI install
where nobody opens the window, pinning it would leave `has_valid_password()`
false and the machine unreachable. A unit test and a customisation check both
assert the override stays absent.

---

## 1b. First-run permanent password

RustDesk stores the permanent password **hashed** — that is why the main window
shows `-` once one is set. The plaintext exists only at the moment it is
chosen, and upstream never creates one by itself.

`flutter/lib/datasoftware.dart` therefore, on the first start of an *installed*
client, generates a 14-character password with `Random.secure()`, applies it
with `mainSetPermanentPasswordWithResult`, and shows it once in a dialog with a
copy button. Its only hook into upstream code is one call in
`desktop_home_page.dart`'s `initState`.

Properties worth knowing:

- **Per machine.** One compromised endpoint exposes nothing else. A single
  shared password baked into the build would have to sit in the binary in
  readable form for the dialog to display it, and anyone with the installer
  could extract it.
- **Never stored in plaintext** and never leaves the machine.
- **Dismissing without confirming is safe.** The next start generates and shows
  a *new* password rather than pretending to recover the old one, which is
  impossible. So the dialog always shows the password actually in effect.
- The acknowledgement is recorded in the local option
  `datasoftware-initial-password-acknowledged`.
- The alphabet omits `0/O` and `1/l/I`, because this gets read off a screen and
  typed somewhere else.

### Locking the password

`disable-change-permanent-password` **is** set, but only after a password has
been provisioned. It cannot be unconditional: the flag makes
`Config::set_permanent_password()` return false, so switching it on from the
start would block this generator too and leave the machine with no permanent
password and no way to set one.

`apply_builtin_config()` therefore turns it on only when the acknowledgement
local option is `Y`. Before the first confirmation the lock is off so the
password can be generated; afterwards it is on. That ordering is also what
keeps "dismiss the dialog and get a fresh password next start" working.

It is a *local* option, so it is evaluated per process, which is deliberate:

- **The UI** reads its own `LocalConfig`, so `Settings → Security` hides the
  password control — it already honours this flag upstream — and
  `set_permanent_password_with_result()` refuses before the IPC to the service
  is even attempted. That is the only route the customer has.
- **The service** does not get the flag, which leaves
  `rustdesk.exe --password <new>` working as an administrative reset. Nothing
  in the service changes the password on its own.

The key literal is duplicated in `src/datasoftware.rs` (`INITIAL_PASSWORD_ACK`)
and `flutter/lib/datasoftware.dart` (`kDataSoftwareInitialPasswordAck`). A
drift would silently disable the lock, so `check_customisation.py` compares
them.

Dialog strings are translated; Slovak lives in `src/lang/sk.rs`, English in
`src/lang/en.rs`.

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

This is mostly automated. Three pieces do the work:

| Piece | What it does |
| --- | --- |
| `.github/datasoftware/check_customisation.py` | Verifies every invariant below that can be checked mechanically. Runs in seconds, needs no toolchain. |
| `.github/datasoftware/merge_upstream.sh` | Does the merge, auto-resolves the version conflict, runs the checks, and refuses to commit a merge that breaks them. |
| `.github/workflows/datasoftware-upstream-sync.yml` | Weekly: finds the newest upstream release, runs the merge, and either opens a PR or opens an issue describing the conflicts. Never pushes to the DataSoftware branch. |

There is also a Claude Code agent, `.claude/agents/upstream-sync.md`, for the
conflicts that need judgement.

### The automated path

The scheduled workflow opens a pull request when a merge is clean. Review it,
run the Windows build, test on Windows, then merge. You can also start it by
hand from the Actions tab, optionally naming a specific tag.

### By hand

```bash
git remote add upstream https://github.com/rustdesk/rustdesk.git   # once
git fetch upstream --tags
git checkout -b upstream-sync/1.5.0 datasoftware-custom-client
bash .github/datasoftware/merge_upstream.sh 1.5.0
```

The script auto-resolves the one conflict that happens on **every** upstream
release — `Cargo.toml` and `Cargo.lock`, because upstream bumps the version and
we carry a `-N` build suffix — by taking upstream's files and re-applying our
version as `<upstream version>-1`. Those are the only lines we change in them.
Any other conflict is aborted and reported, because guessing at a conflict in
`src/common.rs` is how the auto-updater ends up pointing back at
`rustdesk/rustdesk`.

### What the automation cannot do

`check_customisation.py` is pattern matching. It proves the hooks are *present*;
it cannot prove upstream did not change what the surrounding code *means*. So
after any merge, read the upstream diff for `src/common.rs`, `src/updater.rs`,
`src/platform/windows.rs` and `res/msi/preprocess.py`, and check, in this order:

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
4. **`keys::OPTION_*` constants** — `check_customisation.py` verifies these
   resolve from the crate `src/datasoftware.rs` imports them from, so a move is
   caught before the build. It has already happened: in 1.4.9 they live in
   `libs/hbb_common/src/config.rs`, but on `master` (1.5.0-dev) all of
   `OPTION_CUSTOM_RENDEZVOUS_SERVER`, `OPTION_API_SERVER`, `OPTION_KEY` and
   `OPTION_ALLOW_AUTO_UPDATE` moved to `libs/base/src/config/keys.rs`, leaving
   only "the keys hbb_common itself references" behind. **Merging 1.5.0 will
   therefore require changing the `use` in `src/datasoftware.rs` from
   `hbb_common::config::{self, keys, Config}` to import `keys` from `base`
   instead** — a one-line change. What the check cannot tell you is whether a
   key moved to a *different settings map*, which would silently change whether
   a value is enforced; verify that by hand against `KEYS_SETTINGS`.
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
5. The window, taskbar, tray and Add/Remove Programs all show the DataSoftware
   logo, not the RustDesk one. The tray is the one most likely to be missed: it
   comes from `flutter_assets/assets/icon.png`, not from the `.ico`.
6. The peer list has no "Discovered" tab, and it cannot be re-enabled.
7. On the very first start a dialog shows a 14-character permanent password.
   Confirm it, restart, and check it does not appear again. Then connect from
   another machine using that password.
8. After confirming, `Settings → Security` no longer offers to change the
   password. `rustdesk.exe --password <new>` from an elevated prompt still
   works, which is the intended administrative reset.
9. `%APPDATA%\DataSoftware-Remote\config\RustDesk2.toml` contains no
   `custom-rendezvous-server` entry — the value comes from the built-in
   override, not from the user's file.
10. Auto-update: with a newer release published, the service picks it up within
    24 h. To test immediately, install an older build and watch
    `%APPDATA%\DataSoftware-Remote\log\` — the update check runs 30 s after the
    service starts.
11. Confirm in the log, or with a network capture, that the client contacts
    `api.github.com/repos/PeterLinuxOSS/rustdesk` and never
    `api.rustdesk.com/version/latest`.

---

## 10. Licence

RustDesk is AGPL-3.0. This fork is a modified version of it and stays
AGPL-3.0; the corresponding source is this public repository.
