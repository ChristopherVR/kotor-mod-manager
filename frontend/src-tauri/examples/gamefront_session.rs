//! Download-only live probe using the production GameFront browser module.
//! cargo run --example gamefront_session -- signin
//! Close it after signing in with Stay logged in, then restart with vurt/remote.
//! No Python backend or game installation is started.
#[path = "../src/gamefront.rs"]
mod gamefront;
use tauri::Manager;

#[cfg(windows)]
fn download_diagnostics(window: &tauri::WebviewWindow) {
    use webview2_com::Microsoft::Web::WebView2::Win32::*;
    use webview2_com::{DownloadStartingEventHandler, StateChangedEventHandler};
    use windows::core::Interface;
    let _ = window.with_webview(|webview| unsafe {
        let result = (|| -> windows::core::Result<()> {
            let core = webview
                .controller()
                .CoreWebView2()?
                .cast::<ICoreWebView2_4>()?;
            core.add_DownloadStarting(
                &DownloadStartingEventHandler::create(Box::new(|_, args| {
                    if let Some(args) = args {
                        args.DownloadOperation()?.add_StateChanged(
                            &StateChangedEventHandler::create(Box::new(|op, _| {
                                if let Some(op) = op {
                                    let mut state = COREWEBVIEW2_DOWNLOAD_STATE::default();
                                    op.State(&mut state)?;
                                    if state == COREWEBVIEW2_DOWNLOAD_STATE_INTERRUPTED {
                                        let mut reason =
                                            COREWEBVIEW2_DOWNLOAD_INTERRUPT_REASON::default();
                                        op.InterruptReason(&mut reason)?;
                                        eprintln!("Download interruption reason: {}", reason.0);
                                    }
                                }
                                Ok(())
                            })),
                            &mut Default::default(),
                        )?;
                    }
                    Ok(())
                })),
                &mut Default::default(),
            )?;
            Ok(())
        })();
        if result.is_err() {
            eprintln!("Download diagnostics unavailable");
        }
    });
}

fn main() {
    let mode = std::env::args().nth(1).unwrap_or_else(|| "signin".into());
    let request = match mode.as_str() {
        "signin" => None,
        "vurt" | "remote" => {
            let (game, slug) = if mode == "vurt" {
                (
                    "knights-of-the-old-republic",
                    "vurt-s-k1-hi-res-ebon-hawk-retexture",
                )
            } else {
                ("knights-of-the-old-republic-ii", "remote-tells-influence")
            };
            let root = std::env::var_os("USERPROFILE")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(std::env::temp_dir)
                .join("Downloads/KOTOR_GameFront_Session_Test")
                .join(&mode);
            let id = format!(
                "{:032x}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            );
            Some(gamefront::Request {
                id,
                url: format!("https://www.gamefront.com/games/{game}/file/{slug}"),
                destination: root,
                name: mode.clone(),
            })
        }
        _ => panic!("Expected signin, vurt or remote"),
    };
    let mut context = tauri::generate_context!();
    context.config_mut().app.windows.clear();
    tauri::Builder::default()
        .manage(gamefront::Session::default())
        .setup(move |app| {
            gamefront::open(app.handle(), request.clone()).map_err(std::io::Error::other)?;
            #[cfg(windows)]
            if let Some(window) = app.get_webview_window("gamefront-browser") {
                download_diagnostics(&window);
            }
            // Diagnostic metadata only: never export cookie values or headers.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(15));
                if let Some(window) = handle.get_webview_window("gamefront-browser") {
                    if let Ok(cookies) =
                        window.cookies_for_url("https://www.gamefront.com".parse().unwrap())
                    {
                        for cookie in cookies {
                            println!(
                                "cookie={} secure={:?} http_only={:?} expires={:?}",
                                cookie.name(),
                                cookie.secure(),
                                cookie.http_only(),
                                cookie.expires()
                            );
                        }
                    }
                }
            });
            Ok(())
        })
        .run(context)
        .expect("GameFront session probe failed");
}
