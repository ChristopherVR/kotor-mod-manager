//! GameFront stays in a dedicated browser profile. No cookies, passwords or
//! signed download URLs cross the frontend/backend bridge.
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex, MutexGuard,
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::webview::{DownloadEvent, NewWindowResponse, PageLoadEvent};
use tauri::{
    Emitter, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};

const LABEL: &str = "gamefront-browser";
const ACCOUNT_URL: &str = "https://www.gamefront.com/account";
/// GameFront only keeps a player signed in between visits when they tick
/// "Stay logged in", which sets this cookie. Its presence is what "signed in"
/// means for the installer, because that is what makes later downloads work.
const REMEMBER_COOKIE: &str = "remember_web_";
/// How long a GameFront page may stay blank before the player is told how to
/// get out of it. Slow verification pages usually finish well inside this.
const LOAD_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Deserialize, Serialize)]
pub struct Request {
    pub id: String,
    pub url: String,
    pub destination: PathBuf,
    pub name: String,
}

#[derive(Default)]
pub struct Session {
    active: Mutex<Option<Request>>,
    transfers: Mutex<HashMap<PathBuf, (String, PathBuf, String)>>,
    /// Bumped on every navigation; a page-load watchdog only reports when no
    /// newer navigation or finished load has happened since it started.
    load_generation: AtomicU64,
    loaded_generation: AtomicU64,
    /// Set when the installer closes the window itself, so that is not
    /// mistaken for the player giving up on a download.
    closing_quietly: AtomicBool,
    /// Serializes sign-in checks so two page loads cannot race each other.
    account: Mutex<()>,
}

/// A panic while a lock was held must not take every later download with it.
/// The guarded data is plain bookkeeping, so reusing it is always safe.
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn site_url(url: &Url) -> bool {
    url.scheme() == "https"
        && url.port_or_known_default() == Some(443)
        && url.username().is_empty()
        && url.password().is_none()
        && url
            .host_str()
            .is_some_and(|h| h == "gamefront.com" || h.ends_with(".gamefront.com"))
}

fn request_url(request: &Request) -> Result<Url, String> {
    let mut url = Url::parse(&request.url).map_err(|_| "Invalid GameFront URL")?;
    if !site_url(&url)
        || url.host_str() != Some("www.gamefront.com")
        || !url.path().starts_with("/games/")
        || !url.path().contains("/file/")
        || url.query().is_some()
        || url.fragment().is_some()
        || request.id.len() != 32
        || !request.id.bytes().all(|b| b.is_ascii_hexdigit())
        || !request.destination.is_absolute()
    {
        return Err("Invalid GameFront download request".into());
    }
    let path = url.path().trim_end_matches('/').to_owned();
    if !path.ends_with("/download") {
        url.set_path(&format!("{path}/download"));
    }
    Ok(url)
}

fn archive_name(path: &Path) -> Option<String> {
    let name = path.file_name()?.to_str()?;
    if name.starts_with('.')
        || name
            .chars()
            .any(|c| c.is_control() || "<>:\"/\\|?*".contains(c))
    {
        return None;
    }
    let ext = path.extension()?.to_str()?.to_ascii_lowercase();
    ["zip", "rar", "7z"]
        .contains(&ext.as_str())
        .then(|| name.to_owned())
}

fn archive_header(path: &Path) -> bool {
    let mut buf = [0; 8];
    let Ok(mut file) = fs::File::open(path) else {
        return false;
    };
    let Ok(n) = file.read(&mut buf) else {
        return false;
    };
    let b = &buf[..n];
    b.starts_with(b"PK\x03\x04")
        || b.starts_with(b"PK\x05\x06")
        || b.starts_with(b"Rar!\x1a\x07\x00")
        || b.starts_with(b"Rar!\x1a\x07\x01\x00")
        || b.starts_with(b"7z\xbc\xaf\x27\x1c")
}

fn download_path(path: &Path) -> PathBuf {
    // Normalize the directory even when a failed browser transfer has already
    // removed its file. WebView2 strips Windows' extended-path prefix.
    if let (Some(parent), Some(name)) = (path.parent(), path.file_name()) {
        if let Ok(parent) = fs::canonicalize(parent) {
            return parent.join(name);
        }
    }
    path.to_owned()
}

fn report(app: &tauri::AppHandle, message: &str) {
    // Deliberately exclude raw URLs and cookie values from errors/events.
    eprintln!("[GameFront] {message}");
    let _ = app.emit_to("main", "gamefront-message", message);
}

pub fn open(app: &tauri::AppHandle, request: Option<Request>) -> Result<(), String> {
    let state = app.state::<Session>();
    let mut target: Url = ACCOUNT_URL.parse().unwrap();
    let mut navigate = false;
    if let Some(mut req) = request {
        target = request_url(&req)?;
        fs::create_dir_all(&req.destination).map_err(|_| "Cannot create mod download folder")?;
        // WebView2 rejects mixed/forward separators even when std::fs accepts
        // the path. Canonicalization also resolves the actual directory once.
        req.destination =
            fs::canonicalize(&req.destination).map_err(|_| "Cannot resolve mod download folder")?;
        let mut active = lock(&state.active);
        navigate = active.as_ref().map(|r| &r.id) != Some(&req.id);
        *active = Some(req);
    } else if let Some(req) = lock(&state.active).as_ref() {
        target = request_url(req)?;
    }
    if let Some(window) = app.get_webview_window(LABEL) {
        if navigate {
            // Start the watchdog before navigating so a very fast page load
            // can never finish ahead of it and trigger a false warning.
            watch_page_load(app);
        }
        let reused = (!navigate || window.navigate(target.clone()).is_ok())
            && window.show().is_ok();
        if reused {
            let _ = window.unminimize();
            let _ = window.set_focus();
            return Ok(());
        }
        // The old window is broken (crashed browser process, lost handle).
        // Throw it away and build a fresh one instead of failing the download.
        eprintln!("[GameFront] Replacing an unresponsive GameFront window");
        let _ = window.destroy();
    }
    watch_page_load(app);
    build(app, target, true)?;
    Ok(())
}

fn build(app: &tauri::AppHandle, target: Url, visible: bool) -> Result<WebviewWindow, String> {
    let profile = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "Profile folder unavailable")?
        .join("gamefront-profile");
    fs::create_dir_all(&profile).map_err(|_| "Cannot create GameFront profile")?;
    app.state::<Session>()
        .closing_quietly
        .store(false, Ordering::SeqCst);
    let window = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::External(target))
        .title("GameFront")
        .inner_size(1100.0, 780.0)
        .center()
        .visible(visible)
        .data_directory(profile)
        .on_navigation(site_url)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .on_page_load(|window, payload| {
            if payload.event() == PageLoadEvent::Finished {
                let state = window.app_handle().state::<Session>();
                let current = state.load_generation.load(Ordering::SeqCst);
                state.loaded_generation.store(current, Ordering::SeqCst);
                // Reading cookies from this thread would deadlock WebView2.
                let app = window.app_handle().clone();
                std::thread::spawn(move || {
                    refresh_account(&app);
                });
            }
        })
        .on_download(|webview, event| {
            let app = webview.app_handle();
            let state = app.state::<Session>();
            match event {
                DownloadEvent::Requested { url, destination } => {
                    let active = lock(&state.active);
                    let Some(req) = active.as_ref() else {
                        report(app, "Start a mod download from the installer first.");
                        return false;
                    };
                    if !site_url(&url) || url.host_str() != Some("osiris.gamefront.com") {
                        report(app, "GameFront returned an unsupported download host.");
                        return false;
                    }
                    let Some(name) = archive_name(destination) else {
                        report(app, "GameFront did not offer a supported mod archive.");
                        return false;
                    };
                    let staging = req.destination.join(format!(".gamefront-{}", req.id));
                    if fs::create_dir_all(&staging).is_err() {
                        report(app, "Could not prepare the mod folder for this download. Check the disk has free space.");
                        return false;
                    }
                    // Keep the archive extension for the browser's download
                    // handling. The nested staging folder is invisible to the
                    // installer's top-level archive watcher until promotion.
                    let part = staging.join(&name);
                    let final_path = req.destination.join(&name);
                    // Never overwrite a completed file
                    // or a second download that is already in progress.
                    let mut transfers = lock(&state.transfers);
                    if final_path.exists() || part.exists() || transfers.contains_key(&part) {
                        report(app, "This archive is already downloaded or downloading.");
                        return false;
                    }
                    transfers.insert(part.clone(), (req.id.clone(), final_path, url.to_string()));
                    *destination = part;
                    true
                }
                DownloadEvent::Finished { url, path, success } => {
                    let Some(path) = path else {
                        // Failed downloads may omit their path. Only one job
                        // can be active; clear its incomplete files for retry.
                        let mut transfers = lock(&state.transfers);
                        transfers.retain(|part, (_, _, source)| {
                            if source == url.as_str() {
                                let _ = fs::remove_file(part);
                                false
                            } else { true }
                        });
                        report(app, "GameFront download failed. Retry the download in the GameFront window.");
                        return true;
                    };
                    let path = download_path(&path);
                    let transfer = lock(&state.transfers).remove(&path);
                    if let Some((id, final_path, _)) = transfer {
                        let active = lock(&state.active);
                        let current = active.as_ref().is_some_and(|r| r.id == id);
                        if !success || !current {
                            let _ = fs::remove_file(&path);
                            report(app, "GameFront download was cancelled. Retry the download in the GameFront window.");
                        } else if !archive_header(&path) {
                            let _ = fs::remove_file(&path);
                            report(app, "GameFront returned a page instead of an archive. Complete verification and retry.");
                        } else if !final_path.exists() && fs::rename(&path, &final_path).is_ok() {
                            report(app, "GameFront archive received. Continuing the installer.");
                        } else {
                            report(app, "GameFront archive finished but could not be moved to the mod folder.");
                        }
                    }
                    true
                }
                _ => true,
            }
        })
        .build()
        .map_err(|_| "Could not create the GameFront browser")?;
    let handle = app.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::Destroyed = event {
            let state = handle.state::<Session>();
            let quiet = state.closing_quietly.swap(false, Ordering::SeqCst);
            // The player closed the window while a mod was still waiting on
            // it. Let the installer carry on in their regular browser instead.
            if !quiet && lock(&state.active).is_some() {
                let _ = handle.emit_to("main", "gamefront-closed", ());
            }
        }
    });
    Ok(window)
}

fn account_file(app: &tauri::AppHandle) -> Option<PathBuf> {
    Some(app.path().app_local_data_dir().ok()?.join("gamefront-account.json"))
}

fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// The sign-in last seen in the GameFront window. The browser profile can only
/// be read while that window exists, so this remembers it in between.
fn saved_sign_in(app: &tauri::AppHandle) -> bool {
    let Some(text) = account_file(app).and_then(|p| fs::read_to_string(p).ok()) else {
        return false;
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) else {
        return false;
    };
    match value.get("expires").and_then(|e| e.as_i64()) {
        Some(expires) => expires > now(),
        None => value.get("signed_in").and_then(|s| s.as_bool()) == Some(true),
    }
}

/// `Some(expiry)` records a sign-in, `None` forgets it.
fn save_sign_in(app: &tauri::AppHandle, sign_in: Option<Option<i64>>) {
    let Some(path) = account_file(app) else {
        return;
    };
    match sign_in {
        Some(expires) => {
            let body = serde_json::json!({ "signed_in": true, "expires": expires });
            let _ = fs::write(path, body.to_string());
        }
        None => {
            let _ = fs::remove_file(path);
        }
    }
}

/// Read the sign-in straight from the GameFront window: `None` when it cannot
/// be read, `Some(None)` when signed out, `Some(Some(expiry))` when signed in.
/// Must not run on the main thread.
fn live_sign_in(window: &WebviewWindow) -> Option<Option<Option<i64>>> {
    let cookies = window.cookies_for_url(ACCOUNT_URL.parse().ok()?).ok()?;
    Some(
        cookies
            .iter()
            .find(|c| c.name().starts_with(REMEMBER_COOKIE))
            .map(|c| c.expires_datetime().map(|t| t.unix_timestamp())),
    )
}

/// Check whether the player is signed in, remember it, and tell the installer
/// when it changes. Signing in from Settings closes the window again by
/// itself, because there is nothing left to do in it.
fn refresh_account(app: &tauri::AppHandle) -> bool {
    let state = app.state::<Session>();
    let _guard = lock(&state.account);
    let before = saved_sign_in(app);
    let Some(window) = app.get_webview_window(LABEL) else {
        return before;
    };
    // A hidden window only exists while signing out.
    if !window.is_visible().unwrap_or(false) {
        return before;
    }
    let Some(live) = live_sign_in(&window) else {
        return before;
    };
    let after = live.is_some();
    save_sign_in(app, live);
    if after != before {
        let _ = app.emit_to("main", "gamefront-account", after);
        if after && lock(&state.active).is_none() {
            close(app);
        }
    }
    after
}

/// Forget the GameFront sign-in by wiping the window's saved browser data.
fn sign_out(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<Session>();
    let _guard = lock(&state.account);
    let existing = app.get_webview_window(LABEL);
    let window = match &existing {
        Some(window) => window.clone(),
        // The profile can only be cleared through a browser that uses it.
        None => build(app, "about:blank".parse().unwrap(), false)?,
    };
    let cleared = window.clear_all_browsing_data().is_ok() && {
        // Clearing finishes in the background. Wait until the sign-in is
        // really gone before reporting success, so the button never lies.
        (0..50).any(|_| {
            let gone = live_sign_in(&window) == Some(None);
            if !gone {
                std::thread::sleep(Duration::from_millis(100));
            }
            gone
        })
    };
    if existing.is_some() {
        // Show the sign-in page again in a window the player already had open.
        let _ = window.navigate(ACCOUNT_URL.parse().unwrap());
    } else {
        close(app);
    }
    if !cleared {
        return Err("Could not sign out of GameFront. Please try again.".into());
    }
    save_sign_in(app, None);
    let _ = app.emit_to("main", "gamefront-account", false);
    Ok(())
}

/// Tell the player what to do if GameFront never finishes loading, so a blank
/// window is never a dead end.
fn watch_page_load(app: &tauri::AppHandle) {
    let state = app.state::<Session>();
    let generation = state.load_generation.fetch_add(1, Ordering::SeqCst) + 1;
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(LOAD_TIMEOUT);
        let state = app.state::<Session>();
        let still_current = state.load_generation.load(Ordering::SeqCst) == generation;
        let loaded = state.loaded_generation.load(Ordering::SeqCst) >= generation;
        if still_current && !loaded && app.get_webview_window(LABEL).is_some() {
            report(
                &app,
                "GameFront is taking a long time to load. If its window stays blank, close it and the installer will open GameFront in your regular browser instead.",
            );
        }
    });
}

/// Close the GameFront window for good. Used by the installer's own close
/// button and when the main window goes away, so it can never be left behind.
pub fn close(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(LABEL) {
        app.state::<Session>()
            .closing_quietly
            .store(true, Ordering::SeqCst);
        if window.destroy().is_err() {
            let _ = window.close();
        }
    }
}

// These commands must stay async. A synchronous command runs on the main
// thread, and creating a browser window from there deadlocks WebView2 on
// Windows: the window appears but stays white and cannot be closed (#114).
#[tauri::command]
pub async fn open_gamefront(
    window: WebviewWindow,
    app: tauri::AppHandle,
    request: Option<Request>,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Only the installer can open downloads".into());
    }
    open(&app, request)
}

#[tauri::command]
pub async fn finish_gamefront(
    window: WebviewWindow,
    app: tauri::AppHandle,
    id: String,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Only the installer can finish downloads".into());
    }
    let state = app.state::<Session>();
    let mut active = lock(&state.active);
    if active.as_ref().is_some_and(|r| r.id == id) {
        *active = None;
    }
    Ok(())
}

#[tauri::command]
pub async fn close_gamefront(window: WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Only the installer can close GameFront".into());
    }
    close(&app);
    Ok(())
}

/// Whether the player is signed in to GameFront.
#[tauri::command]
pub async fn gamefront_account(
    window: WebviewWindow,
    app: tauri::AppHandle,
) -> Result<bool, String> {
    if window.label() != "main" {
        return Err("Only the installer can check GameFront".into());
    }
    Ok(refresh_account(&app))
}

#[tauri::command]
pub async fn sign_out_gamefront(window: WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Only the installer can sign out of GameFront".into());
    }
    sign_out(&app)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn poisoned_locks_are_recovered() {
        let mutex = std::sync::Arc::new(Mutex::new(1));
        let poisoner = mutex.clone();
        let _ = std::thread::spawn(move || {
            let _guard = poisoner.lock().unwrap();
            panic!("simulated crash while holding the lock");
        })
        .join();
        assert!(mutex.is_poisoned());
        assert_eq!(*lock(&mutex), 1);
    }
    #[test]
    fn completed_and_failed_paths_match_the_transfer_key() {
        let root = std::env::temp_dir().join(format!("gamefront-path-test-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let callback_path = root.join("mod.zip");
        let transfer_key = fs::canonicalize(&root).unwrap().join("mod.zip");
        // A failed transfer may report a path after removing its partial file.
        assert_eq!(download_path(&callback_path), transfer_key);
        fs::write(&callback_path, b"PK\x03\x04payload").unwrap();
        assert_eq!(download_path(&callback_path), transfer_key);
        fs::remove_file(callback_path).unwrap();
        fs::remove_dir(root).unwrap();
    }
    #[test]
    fn reject_untrusted_destinations_and_urls() {
        let mut req = Request {
            id: "a".repeat(32),
            url: "https://www.gamefront.com/games/kotor/file/mod".into(),
            destination: std::env::temp_dir(),
            name: "test".into(),
        };
        assert!(request_url(&req).unwrap().path().ends_with("/download"));
        for url in [
            "https://www.gamefront.com.evil.test/games/k/file/m",
            "http://www.gamefront.com/games/k/file/m",
            "https://user@www.gamefront.com/games/k/file/m",
            "https://www.gamefront.com/games/k/file/m?token=x",
        ] {
            req.url = url.into();
            assert!(request_url(&req).is_err());
        }
        assert!(!site_url(
            &"https://gamefront.com.evil.test/".parse().unwrap()
        ));
    }
    #[test]
    fn only_archive_filenames_are_accepted() {
        assert_eq!(
            archive_name(Path::new("mod.rar")).as_deref(),
            Some("mod.rar")
        );
        for name in [
            "mod.exe",
            "mod.rar:stream",
            ".hidden.zip",
            "bad?.zip",
            "mod.html",
        ] {
            assert!(archive_name(Path::new(name)).is_none());
        }
    }
    #[test]
    fn html_and_partial_downloads_are_not_archives() {
        let path =
            std::env::temp_dir().join(format!("gamefront-header-test-{}", std::process::id()));
        for bad in [b"<html>Security Check</html>".as_slice(), b"PK", b""] {
            fs::write(&path, bad).unwrap();
            assert!(!archive_header(&path));
        }
        fs::write(&path, b"Rar!\x1a\x07\x00payload").unwrap();
        assert!(archive_header(&path));
        fs::remove_file(path).unwrap();
    }
}
