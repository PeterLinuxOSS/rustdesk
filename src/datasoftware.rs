// ===========================================================================
// DataSoftware custom client configuration
// ===========================================================================
//
// This module is the ONLY place that carries DataSoftware-specific behaviour.
// Everything else in the tree stays as close to upstream RustDesk as possible
// so that merging a new upstream release is a small, reviewable operation.
//
// Outside of this file the fork only contains these hooks:
//
//   * src/lib.rs      - `pub mod datasoftware;`
//   * src/common.rs   - `load_custom_client()` calls `apply_builtin_config()`
//   * src/common.rs   - `do_check_software_update()` asks this module for the
//                       latest release instead of `api.rustdesk.com`
//
// See DATASOFTWARE_BUILD.md for the full maintenance procedure.

use hbb_common::{
    bail,
    config::{self, keys, Config},
    log,
    tls::{get_cached_tls_type, upsert_tls_cache, TlsType},
    ResultType,
};

use crate::hbbs_http::{create_http_client_async, get_url_for_tls};

/// Application name. Upstream derives a lot from this value: window title,
/// install directory, installed executable name, Windows service name, config
/// directory, the Add/Remove Programs entry, the strings produced by
/// `src/lang.rs`, and `is_custom_client()` (simply `get_app_name() != "RustDesk"`).
///
/// It must NOT contain a space. Upstream builds Windows shell commands with the
/// name interpolated unquoted - `sc create {app_name} ...`,
/// `sc stop/delete/start {app_name}`, `taskkill /F /IM {app_name}.exe` in
/// `src/platform/windows.rs` (17 places), and `res/msi/preprocess.py` runs the
/// executable through cmd.exe without quoting its path. A space silently splits
/// the service name and breaks installation. Upstream states the same
/// constraint in `src/lang.rs`: "app_name only contains alphanumeric and hyphen".
///
/// The nicer spaced form "DataSoftware Remote" is used where it is purely
/// cosmetic and safe: the Windows executable metadata in
/// `flutter/windows/runner/Runner.rc`.
pub const APP_NAME: &str = "DataSoftware-Remote";

/// Company website, used for user-visible "about" style information.
pub const WEBSITE: &str = "https://datasoftware.sk";

/// ID / rendezvous server (hbbs).
pub const ID_SERVER: &str = "api.datasoftware.sk";

/// API server (hbbs web API).
pub const API_SERVER: &str = "https://remote.datasoftware.sk";

/// Relay server. Empty means "automatic": the ID server tells the client which
/// relay to use. Do not hard-code a relay here unless the deployment needs one.
pub const RELAY_SERVER: &str = "";

/// Public key of the self-hosted RustDesk server.
/// This is the PUBLIC half only - it is meant to be shipped inside the client.
/// The server's private key must never be added to this repository.
pub const PUBLIC_KEY: &str = "7yMWvosWrAbR2iUFsvbyL0YrMx9P839UfShu+bdwMGg=";

// ---------------------------------------------------------------------------
// Update source
// ---------------------------------------------------------------------------
// The stock client asks `https://api.rustdesk.com/version/latest`, which
// answers with a `rustdesk/rustdesk` release URL. This fork must never do that,
// so version discovery is replaced by a direct query against our own GitHub
// repository. There is deliberately NO fallback to `rustdesk/rustdesk`.

/// GitHub owner of the repository that serves DataSoftware Remote updates.
pub const UPDATE_OWNER: &str = "PeterLinuxOSS";

/// GitHub repository name that serves DataSoftware Remote updates.
pub const UPDATE_REPO: &str = "rustdesk";

/// GitHub requires a User-Agent header on every API request.
const UPDATE_USER_AGENT: &str = "DataSoftware-Remote-Updater";

#[inline]
pub fn latest_release_api_url() -> String {
    format!("https://api.github.com/repos/{UPDATE_OWNER}/{UPDATE_REPO}/releases/latest")
}

#[inline]
pub fn release_tag_url(tag: &str) -> String {
    format!("https://github.com/{UPDATE_OWNER}/{UPDATE_REPO}/releases/tag/{tag}")
}

/// Apply the built-in DataSoftware configuration.
///
/// This is the fork's replacement for upstream's signed `custom.txt` bundle
/// (`read_custom_client()`), which cannot be used here because it is verified
/// against a RustDesk-owned signing key. The end state is the same: the values
/// are layered into the in-memory settings maps.
///
/// Nothing is written to the user's configuration file, so unrelated user
/// preferences are never touched, on first start or on any later start.
pub fn apply_builtin_config() {
    *config::APP_NAME.write().unwrap() = APP_NAME.to_owned();

    // Enforced. These identify the DataSoftware infrastructure; a wrong value
    // makes the client unusable, so they go into OVERWRITE_SETTINGS - the same
    // map upstream fills from a custom client's "override-settings" block.
    // Being in this map also means `Config::set_option()` refuses to persist a
    // different value, so the UI cannot drift away from the deployment.
    {
        let mut overwrite = config::OVERWRITE_SETTINGS.write().unwrap();
        overwrite.insert(
            keys::OPTION_CUSTOM_RENDEZVOUS_SERVER.to_owned(),
            ID_SERVER.to_owned(),
        );
        overwrite.insert(keys::OPTION_API_SERVER.to_owned(), API_SERVER.to_owned());
        overwrite.insert(keys::OPTION_KEY.to_owned(), PUBLIC_KEY.to_owned());
        // Empty on purpose: keeps relay selection automatic and prevents a
        // stale relay from an earlier configuration from being used.
        overwrite.insert(
            keys::OPTION_RELAY_SERVER.to_owned(),
            RELAY_SERVER.to_owned(),
        );
    }

    // Not enforced, only a default: automatic updates are on out of the box,
    // but an administrator can still switch them off on a particular machine.
    {
        let mut defaults = config::DEFAULT_SETTINGS.write().unwrap();
        defaults.insert(keys::OPTION_ALLOW_AUTO_UPDATE.to_owned(), "Y".to_owned());
    }

    log::info!(
        "DataSoftware built-in configuration applied (id: {}, api: {}, updates: {}/{})",
        ID_SERVER,
        API_SERVER,
        UPDATE_OWNER,
        UPDATE_REPO
    );
}

#[inline]
async fn request_latest_release(
    client: &reqwest::Client,
    url: &str,
) -> Result<reqwest::Response, reqwest::Error> {
    client
        .get(url)
        .header(reqwest::header::USER_AGENT, UPDATE_USER_AGENT)
        .header(reqwest::header::ACCEPT, "application/vnd.github+json")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .await
}

/// Ask our GitHub repository for the latest published release and return a URL
/// in the exact shape upstream's updater expects:
///
///     https://github.com/<owner>/<repo>/releases/tag/<tag>
///
/// `src/updater.rs` turns that into the download URL by replacing `tag` with
/// `download` and appending `rustdesk-<tag>-<arch>.<exe|msi>`, so the release
/// tag must equal the version used in the asset file names.
///
/// Note: `/releases/latest` ignores drafts and pre-releases, so DataSoftware
/// releases must be published as full releases.
pub async fn fetch_latest_release_url() -> ResultType<String> {
    let url = latest_release_api_url();

    // Mirrors upstream's TLS probing so that proxied or TLS-intercepted
    // corporate networks behave the same as for the stock update check.
    let proxy_conf = Config::get_socks();
    let tls_url = get_url_for_tls(&url, &proxy_conf);
    let tls_type = get_cached_tls_type(tls_url);
    let is_tls_not_cached = tls_type.is_none();
    let tls_type = tls_type.unwrap_or(TlsType::Rustls);
    let client = create_http_client_async(tls_type, false);

    let response = match request_latest_release(&client, &url).await {
        Ok(resp) => {
            upsert_tls_cache(tls_url, tls_type, false);
            resp
        }
        Err(err) => {
            if is_tls_not_cached && err.is_request() {
                let tls_type = TlsType::NativeTls;
                let client = create_http_client_async(tls_type, false);
                let resp = request_latest_release(&client, &url).await?;
                upsert_tls_cache(tls_url, tls_type, false);
                resp
            } else {
                return Err(err.into());
            }
        }
    };

    let status = response.status();
    let bytes = response.bytes().await?;
    if !status.is_success() {
        bail!("Update check failed, {} returned {}", url, status);
    }

    let release: serde_json::Value = serde_json::from_slice(&bytes)?;
    let tag = release
        .get("tag_name")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .trim();
    if tag.is_empty() {
        bail!("Update check failed, no tag_name in the response of {}", url);
    }
    // `updater.rs` builds the download URL with a plain
    // `update_url.replace("tag", "download")`, which would corrupt the URL if
    // the tag itself contained the substring "tag".
    if tag.contains("tag") {
        bail!("Release tag {} must not contain the substring \"tag\"", tag);
    }

    Ok(release_tag_url(tag))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn update_urls_point_at_the_datasoftware_fork() {
        assert_eq!(
            latest_release_api_url(),
            "https://api.github.com/repos/PeterLinuxOSS/rustdesk/releases/latest"
        );
        assert_eq!(
            release_tag_url("1.4.9-1"),
            "https://github.com/PeterLinuxOSS/rustdesk/releases/tag/1.4.9-1"
        );
        assert!(!latest_release_api_url().contains("rustdesk/rustdesk"));
        assert!(!release_tag_url("1.4.9-1").contains("rustdesk/rustdesk"));
    }

    // The updater builds the download URL with a plain `replace("tag", ...)`,
    // so this must keep holding for our repository path.
    #[test]
    fn tag_url_survives_the_updater_rewrite() {
        let tag_url = release_tag_url("1.4.9-1");
        assert_eq!(
            tag_url.replace("tag", "download"),
            "https://github.com/PeterLinuxOSS/rustdesk/releases/download/1.4.9-1"
        );
    }

    // A DataSoftware release must compare as newer than the upstream base
    // version, otherwise `do_check_software_update()` never offers it.
    #[test]
    fn datasoftware_build_suffix_is_newer_than_the_base_version() {
        use hbb_common::get_version_number;
        assert!(get_version_number("1.4.9-1") > get_version_number("1.4.9"));
        assert!(get_version_number("1.4.9-2") > get_version_number("1.4.9-1"));
    }

    // A space in the app name silently breaks `sc create {app_name} ...` and
    // `taskkill /F /IM {app_name}.exe` in src/platform/windows.rs, and the
    // unquoted cmd.exe invocation in res/msi/preprocess.py.
    #[test]
    fn app_name_is_safe_for_windows_shell_commands() {
        assert!(!APP_NAME.contains(' '), "APP_NAME must not contain a space");
        assert!(
            APP_NAME.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'),
            "APP_NAME must be alphanumeric or hyphen only"
        );
    }

    #[test]
    fn builtin_config_is_applied() {
        apply_builtin_config();
        assert_eq!(config::APP_NAME.read().unwrap().as_str(), APP_NAME);
        assert_eq!(
            Config::get_option(keys::OPTION_CUSTOM_RENDEZVOUS_SERVER),
            ID_SERVER
        );
        assert_eq!(Config::get_option(keys::OPTION_API_SERVER), API_SERVER);
        assert_eq!(Config::get_option(keys::OPTION_KEY), PUBLIC_KEY);
        assert_eq!(Config::get_option(keys::OPTION_RELAY_SERVER), "");
        assert!(Config::get_bool_option(keys::OPTION_ALLOW_AUTO_UPDATE));
        // A rebranded app name is what makes upstream treat this as a custom client.
        assert!(crate::is_custom_client());
    }
}
