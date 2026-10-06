// Prevents an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_deep_link::DeepLinkExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
#[cfg(unix)]
use std::os::unix::process::CommandExt as _;

// The Python backend is embedded INTO this executable at compile time, so the
// whole app ships as a single self-contained file. It is extracted to a temp
// dir and launched on startup, then killed on exit.
#[cfg(windows)]
const BACKEND_BYTES: &[u8] =
    include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/binaries/kotor-backend.exe"));
#[cfg(not(windows))]
const BACKEND_BYTES: &[u8] =
    include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/binaries/kotor-backend"));
#[cfg(windows)]
const BACKEND_SUFFIX: &str = ".exe";
#[cfg(not(windows))]
const BACKEND_SUFFIX: &str = "";
const VERSION: &str = env!("CARGO_PKG_VERSION");
const BACKEND_PORT: &str = "8756";

struct BackendChild(Mutex<Option<Child>>);

fn extract_backend() -> std::path::PathBuf {
    let dir = std::env::temp_dir().join("kotor-mod-installer");
    let _ = std::fs::create_dir_all(&dir);
    let path = dir.join(format!("kotor-backend-{}{}", VERSION, BACKEND_SUFFIX));

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
    #[cfg(unix)]
    {
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755));
    }
    path
}

fn spawn_backend() -> Option<Child> {
    let path = extract_backend();
    let mut cmd = Command::new(&path);
    cmd.args(["--host", "127.0.0.1", "--port", BACKEND_PORT]);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    // Own process group, so stopping it also stops the PyInstaller worker.
    #[cfg(unix)]
    cmd.process_group(0);
    // Stop the backend if we crash or are killed, so it cannot hold the port.
    #[cfg(target_os = "linux")]
    unsafe {
        cmd.pre_exec(|| {
            libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
            Ok(())
        });
    }
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("[backend] failed to spawn: {e}");
            None
        }
    }
}

/// Stop the backend. On Linux, signal the whole process group: the launcher's
/// worker child is what holds the port.
fn stop_backend(mut child: Child) {
    #[cfg(unix)]
    {
        let pid = child.id() as libc::pid_t;
        unsafe {
            libc::kill(-pid, libc::SIGTERM);
        }
        std::thread::sleep(std::time::Duration::from_millis(300));
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
        let _ = child.wait();
    }
    #[cfg(not(unix))]
    {
        let _ = child.kill();
    }
}

/// Apply a downloaded update: write a swapper that waits for us to exit, copies
/// the new exe over the current one, relaunches it, and cleans up. Then kill the
/// backend (so it releases the port) and exit so the swap can proceed.
#[tauri::command]
fn apply_update(app: tauri::AppHandle, new_path: String) -> Result<(), String> {
    // An AppImage reports the file to replace in $APPIMAGE.
    let cur = match std::env::var_os("APPIMAGE") {
        Some(p) if cfg!(unix) => std::path::PathBuf::from(p),
        _ => std::env::current_exe().map_err(|e| e.to_string())?,
    };
    let pid = std::process::id();
    let tmp = std::env::temp_dir().join("kotor-mod-installer-update");
    let _ = std::fs::create_dir_all(&tmp);

    #[cfg(windows)]
    {
        let cur_s = cur.display().to_string().replace('\'', "''");
        let new_s = new_path.replace('\'', "''");
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
        cmd.creation_flags(CREATE_NO_WINDOW);
        cmd.spawn().map_err(|e| e.to_string())?;
    }

    #[cfg(unix)]
    {
        // Paths are passed as arguments, never spliced into the script.
        let script = tmp.join("swap.sh");
        let content = "#!/bin/sh\n\
            pid=\"$1\"; new=\"$2\"; cur=\"$3\"\n\
            i=0\n\
            while kill -0 \"$pid\" 2>/dev/null && [ $i -lt 60 ]; do sleep 0.5; i=$((i+1)); done\n\
            sleep 1\n\
            i=0\n\
            until cp -f \"$new\" \"$cur.tmp\" && chmod 755 \"$cur.tmp\" && mv -f \"$cur.tmp\" \"$cur\"; do\n\
              i=$((i+1)); [ $i -ge 10 ] && exit 1; sleep 0.7\n\
            done\n\
            rm -f \"$new\"\n\
            nohup \"$cur\" >/dev/null 2>&1 &\n";
        std::fs::write(&script, content).map_err(|e| e.to_string())?;
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| e.to_string())?;
        Command::new("/bin/sh")
            .arg(&script)
            .arg(pid.to_string())
            .arg(&new_path)
            .arg(&cur)
            .process_group(0)
            .spawn()
            .map_err(|e| e.to_string())?;
    }

    // Kill the backend so it frees port 8756 before the relaunched app starts.
    if let Some(child) = app.state::<BackendChild>().0.lock().unwrap().take() {
        stop_backend(child);
    }
    app.exit(0);
    Ok(())
}

/// Hand an nxm:// link (Nexus "Mod manager download") to the backend, which
/// passes it to the download that is waiting for it. Retries briefly because
/// the backend may still be starting when the app is launched by the link.
fn send_nxm(url: String) {
    post_backend("/api/nexus/nxm", serde_json::json!({ "url": url }).to_string());
}

/// POST a JSON body to the local backend, retrying briefly while it starts.
fn post_backend(path: &'static str, body: String) {
    std::thread::spawn(move || {
        let req = format!(
            "POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\
             Content-Type: application/json\r\nContent-Length: {len}\r\n\
             Connection: close\r\n\r\n{body}",
            path = path, port = BACKEND_PORT, len = body.len(), body = body
        );
        for _ in 0..40 {
            if let Ok(mut s) = std::net::TcpStream::connect(("127.0.0.1", 8756)) {
                if s.write_all(req.as_bytes()).is_ok() {
                    let mut sink = Vec::new();
                    let _ = std::io::Read::read_to_end(&mut s, &mut sink);
                    return;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
    });
}

/// Marks that we hold the nxm:// scheme; on Linux it also records who had it.
fn previous_handler_file() -> std::path::PathBuf {
    std::env::temp_dir().join("kotor-mod-installer").join("nxm-previous-handler")
}

#[cfg(windows)]
const NXM_KEY: &str = r"HKCU\Software\Classes\nxm";

/// Run reg.exe without flashing a console window. True when it succeeded.
#[cfg(windows)]
fn reg_command(args: &[&str]) -> bool {
    Command::new("reg")
        .args(args)
        .creation_flags(CREATE_NO_WINDOW)
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Give nxm:// links back to whatever app handled them before we took them.
fn release_nxm(app: &tauri::AppHandle) {
    #[cfg(target_os = "linux")]
    {
        let file = previous_handler_file();
        // No record means we are not holding the scheme; leave it alone.
        let Ok(previous) = std::fs::read_to_string(&file) else {
            return;
        };
        let previous = previous.trim();
        let restored = !previous.is_empty()
            && Command::new("xdg-mime")
                .args(["default", previous, "x-scheme-handler/nxm"])
                .status()
                .map(|s| s.success())
                .unwrap_or(false);
        if !restored {
            let _ = app.deep_link().unregister("nxm");
        }
        let _ = std::fs::remove_file(file);
    }
    #[cfg(windows)]
    {
        let _ = app;
        let file = previous_handler_file();
        // No record means we are not holding the scheme; leave it alone.
        if !file.exists() {
            return;
        }
        // Not deep_link().unregister(): it also deletes the machine-wide key,
        // which would remove another Nexus manager's registration for good.
        let backup = file.with_extension("reg");
        let _ = reg_command(&["delete", NXM_KEY, "/f"]);
        if backup.exists() {
            let _ = reg_command(&["import", &backup.display().to_string()]);
            let _ = std::fs::remove_file(backup);
        }
        let _ = std::fs::remove_file(file);
    }
    #[cfg(not(any(windows, target_os = "linux")))]
    let _ = app;
}

/// Take nxm:// links (Nexus "Mod manager download"), remembering who had them.
fn claim_nxm(app: &tauri::AppHandle) {
    #[cfg(target_os = "linux")]
    {
        let file = previous_handler_file();
        if !file.exists() {
            let current = Command::new("xdg-mime")
                .args(["query", "default", "x-scheme-handler/nxm"])
                .output()
                .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
                .unwrap_or_default();
            // Never record ourselves (a leftover from a crash) as the "previous" one.
            let previous = if current.to_lowercase().contains("kotor-mod-installer") {
                String::new()
            } else {
                current
            };
            if let Some(dir) = file.parent() {
                let _ = std::fs::create_dir_all(dir);
            }
            let _ = std::fs::write(&file, previous);
        }
    }
    #[cfg(windows)]
    {
        let file = previous_handler_file();
        if !file.exists() {
            if let Some(dir) = file.parent() {
                let _ = std::fs::create_dir_all(dir);
            }
            // Save whoever has nxm:// (Vortex, the Nexus app) so it can be restored.
            let backup = file.with_extension("reg");
            let saved = reg_command(&["export", NXM_KEY, &backup.display().to_string(), "/y"]);
            if !saved {
                let _ = std::fs::remove_file(&backup);
            }
            let _ = std::fs::write(file, "");
        }
    }
    let _ = app.deep_link().register("nxm");
}

/// nxm:// links are for every game on Nexus, so the app only holds them while a
/// free-account download is waiting for its click, then hands them back.
#[tauri::command]
fn set_nxm_handler(app: tauri::AppHandle, enabled: bool) {
    if enabled {
        claim_nxm(&app);
    } else {
        release_nxm(&app);
    }
}

fn main() {
    let builder = tauri::Builder::default();
    // A second launch (the browser opening an nxm:// link) must hand its link to
    // the running app instead of starting another one. Registered first, as the
    // plugin requires.
    #[cfg(any(windows, target_os = "linux", target_os = "macos"))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|_app, _args, _cwd| {}));
    builder
        .plugin(tauri_plugin_deep_link::init())
        .setup(|app| {
            // Undo a claim left behind if the app died while one was held.
            release_nxm(app.handle());
            if let Ok(Some(urls)) = app.deep_link().get_current() {
                for u in urls {
                    send_nxm(u.to_string());
                }
            }
            app.deep_link().on_open_url(|event| {
                for u in event.urls() {
                    send_nxm(u.to_string());
                }
            });
            Ok(())
        })
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendChild(Mutex::new(spawn_backend())))
        .invoke_handler(tauri::generate_handler![apply_update, set_nxm_handler])
        .on_window_event(|window, event| {
            // Only the main window ending means the app is over.
            if window.label() != "main" {
                return;
            }
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(child) = window
                    .app_handle()
                    .state::<BackendChild>()
                    .0
                    .lock()
                    .unwrap()
                    .take()
                {
                    stop_backend(child);
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running the KOTOR Mod Installer");
}
