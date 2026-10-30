//! GameFront stays in a dedicated browser profile. No cookies, passwords or
//! signed download URLs cross the frontend/backend bridge.
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
    sync::Mutex,
};
use tauri::webview::{DownloadEvent, NewWindowResponse};
use tauri::{Emitter, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const LABEL: &str = "gamefront-browser";

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
    let mut target: Url = "https://www.gamefront.com/account".parse().unwrap();
    let mut navigate = false;
    if let Some(mut req) = request {
        target = request_url(&req)?;
        fs::create_dir_all(&req.destination).map_err(|_| "Cannot create mod download folder")?;
        // WebView2 rejects mixed/forward separators even when std::fs accepts
        // the path. Canonicalization also resolves the actual directory once.
        req.destination =
            fs::canonicalize(&req.destination).map_err(|_| "Cannot resolve mod download folder")?;
        let mut active = state
            .active
            .lock()
            .map_err(|_| "GameFront session unavailable")?;
        navigate = active.as_ref().map(|r| &r.id) != Some(&req.id);
        *active = Some(req);
    } else if let Some(req) = state
        .active
        .lock()
        .map_err(|_| "GameFront session unavailable")?
        .as_ref()
    {
        target = request_url(req)?;
    }
    if let Some(window) = app.get_webview_window(LABEL) {
        if navigate {
            window
                .navigate(target)
                .map_err(|_| "Could not open GameFront download")?;
        }
        window.show().map_err(|_| "Could not show GameFront")?;
        let _ = window.set_focus();
        return Ok(());
    }
    let profile = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "Profile folder unavailable")?
        .join("gamefront-profile");
    fs::create_dir_all(&profile).map_err(|_| "Cannot create GameFront profile")?;
    WebviewWindowBuilder::new(app, LABEL, WebviewUrl::External(target))
        .title("GameFront — saved browser session")
        .inner_size(1100.0, 780.0)
        .center()
        .data_directory(profile)
        .on_navigation(site_url)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .on_download(|webview, event| {
            let app = webview.app_handle();
            let state = app.state::<Session>();
            match event {
                DownloadEvent::Requested { url, destination } => {
                    let active = state.active.lock().unwrap();
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
                    if fs::create_dir_all(&staging).is_err() { return false; }
                    // Keep the archive extension for the browser's download
                    // handling. The nested staging folder is invisible to the
                    // installer's top-level archive watcher until promotion.
                    let part = staging.join(&name);
                    let final_path = req.destination.join(&name);
                    // Never overwrite a completed file
                    // or a second download that is already in progress.
                    let mut transfers = state.transfers.lock().unwrap();
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
                        let mut transfers = state.transfers.lock().unwrap();
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
                    let transfer = state.transfers.lock().unwrap().remove(&path);
                    if let Some((id, final_path, _)) = transfer {
                        let active = state.active.lock().unwrap();
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
        .build().map_err(|_| "Could not create the GameFront browser")?;
    Ok(())
}

#[tauri::command]
pub fn open_gamefront(
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
pub fn finish_gamefront(
    window: WebviewWindow,
    app: tauri::AppHandle,
    id: String,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Only the installer can finish downloads".into());
    }
    let state = app.state::<Session>();
    let mut active = state
        .active
        .lock()
        .map_err(|_| "GameFront session unavailable")?;
    if active.as_ref().is_some_and(|r| r.id == id) {
        *active = None;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
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
