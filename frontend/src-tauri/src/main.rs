// Prevents an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Holds the spawned Python backend sidecar so we can terminate it on exit.
struct BackendChild(Mutex<Option<CommandChild>>);

const BACKEND_PORT: &str = "8756";

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendChild(Mutex::new(None)))
        .setup(|app| {
            // Spawn the bundled FastAPI sidecar (kotor-backend) on a fixed port.
            let sidecar = app
                .shell()
                .sidecar("kotor-backend")
                .expect("failed to create `kotor-backend` sidecar command")
                .args(["--host", "127.0.0.1", "--port", BACKEND_PORT]);

            let (mut rx, child) = sidecar.spawn().expect("failed to spawn backend sidecar");
            app.state::<BackendChild>()
                .0
                .lock()
                .unwrap()
                .replace(child);

            // Forward backend stdout/stderr to the Tauri console for debugging.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            print!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprint!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] terminated: {:?}", payload);
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(child) = window
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
