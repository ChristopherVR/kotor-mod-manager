// Prevents an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// The Python backend is embedded INTO this executable at compile time, so the
// whole app ships as a single self-contained .exe. It is extracted to a temp
// dir and launched on startup, then killed on exit.
const BACKEND_BYTES: &[u8] =
    include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/binaries/kotor-backend.exe"));
const VERSION: &str = env!("CARGO_PKG_VERSION");
const BACKEND_PORT: &str = "8756";

struct BackendChild(Mutex<Option<Child>>);

fn extract_backend() -> std::path::PathBuf {
    let dir = std::env::temp_dir().join("kotor-mod-installer");
    let _ = std::fs::create_dir_all(&dir);
    let path = dir.join(format!("kotor-backend-{}.exe", VERSION));

    // (Re)write only if missing or a different size (e.g. after an update).
    let need_write = match std::fs::metadata(&path) {
        Ok(meta) => meta.len() != BACKEND_BYTES.len() as u64,
        Err(_) => true,
    };
    if need_write {
        if let Ok(mut f) = std::fs::File::create(&path) {
            let _ = f.write_all(BACKEND_BYTES);
        }
    }
    path
}

fn spawn_backend() -> Option<Child> {
    let path = extract_backend();
    let mut cmd = Command::new(&path);
    cmd.args(["--host", "127.0.0.1", "--port", BACKEND_PORT]);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("[backend] failed to spawn: {e}");
            None
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendChild(Mutex::new(spawn_backend())))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(mut child) = window
                    .app_handle()
                    .state::<BackendChild>()
                    .0
                    .lock()
                    .unwrap()
                    .take()
                {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running the KOTOR Mod Installer");
}
