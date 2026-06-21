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

/// Apply a downloaded update: write a swapper that waits for us to exit, copies
/// the new exe over the current one, relaunches it, and cleans up. Then kill the
/// backend (so it releases the port) and exit so the swap can proceed.
#[tauri::command]
fn apply_update(app: tauri::AppHandle, new_path: String) -> Result<(), String> {
    let cur = std::env::current_exe().map_err(|e| e.to_string())?;
    let cur_s = cur.display().to_string().replace('\'', "''");
    let new_s = new_path.replace('\'', "''");
    let pid = std::process::id();

    let tmp = std::env::temp_dir().join("kotor-mod-installer-update");
    let _ = std::fs::create_dir_all(&tmp);
    let script = tmp.join("swap.ps1");
    let content = format!(
        "try {{ Wait-Process -Id {pid} -Timeout 30 }} catch {{}}\n\
         Start-Sleep -Milliseconds 800\n\
         for ($i=0; $i -lt 10; $i++) {{ try {{ Copy-Item -LiteralPath '{new}' -Destination '{cur}' -Force; break }} catch {{ Start-Sleep -Milliseconds 700 }} }}\n\
         Start-Process -FilePath '{cur}'\n\
         Remove-Item -LiteralPath '{new}' -Force -ErrorAction SilentlyContinue\n",
        pid = pid, new = new_s, cur = cur_s
    );
    std::fs::write(&script, &content).map_err(|e| e.to_string())?;

    let mut cmd = Command::new("powershell");
    cmd.args([
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", script.to_str().ok_or("bad script path")?,
    ]);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd.spawn().map_err(|e| e.to_string())?;

    // Kill the backend so it frees port 8756 before the relaunched app starts.
    if let Some(mut child) = app.state::<BackendChild>().0.lock().unwrap().take() {
        let _ = child.kill();
    }
    app.exit(0);
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendChild(Mutex::new(spawn_backend())))
        .invoke_handler(tauri::generate_handler![apply_update])
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
