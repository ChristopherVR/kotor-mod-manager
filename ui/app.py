"""KOTOR Mod Installer — queue-based sequential installer UI."""

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
from typing import Optional

import customtkinter as ctk

import config as cfg
from installer.detector import NamespaceOption
from installer.pipeline import ModStatus, Pipeline, PipelineMod
from scraper.build_scraper import BUILD_URLS, BuildMod, scrape_build
from scraper.deadlystream import AuthError, DeadlyStreamClient

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Colour palette
BG        = "#0f0f1a"
PANEL     = "#16213e"
PANEL2    = "#1a1a2e"
ACCENT    = "#0f3460"
HIGHLIGHT = "#e94560"
TEXT      = "#eaeaea"
MUTED     = "#778"
SUCCESS   = "#2ecc71"
WARNING   = "#f39c12"
ERROR_COL = "#e74c3c"
INFO      = "#3498db"

STATUS_COLORS = {
    ModStatus.PENDING:         MUTED,
    ModStatus.DOWNLOADING:     INFO,
    ModStatus.EXTRACTING:      INFO,
    ModStatus.READY:           WARNING,
    ModStatus.INSTALLING:      WARNING,
    ModStatus.WAITING_PATCHER: "#e67e22",
    ModStatus.DONE:            SUCCESS,
    ModStatus.SKIPPED:         MUTED,
    ModStatus.ERROR:           ERROR_COL,
}

BUILD_LABELS = {
    "k1_full":        "KOTOR 1 — Full Build",
    "k1_spoilerfree": "KOTOR 1 — Spoiler-Free",
    "k2_full":        "KOTOR 2 — Full Build",
    "k2_spoilerfree": "KOTOR 2 — Spoiler-Free",
}

BUILD_GAME = {
    "k1_full": "KOTOR1", "k1_spoilerfree": "KOTOR1",
    "k2_full": "KOTOR2", "k2_spoilerfree": "KOTOR2",
}


# ---------------------------------------------------------------------------
# Mod row widget
# ---------------------------------------------------------------------------

class ModRow(ctk.CTkFrame):
    def __init__(self, parent, pm: PipelineMod, **kw):
        super().__init__(parent, fg_color=PANEL2, corner_radius=5, **kw)
        self.pm = pm
        self.grid_columnconfigure(2, weight=1)

        m = pm.build_mod
        order_lbl = ctk.CTkLabel(
            self, text=f"{m.install_order:3d}", width=34,
            font=("Consolas", 10), text_color=MUTED
        )
        order_lbl.grid(row=0, column=0, padx=(6, 2), pady=4)

        self._status_dot = ctk.CTkLabel(
            self, text="●", width=16, font=("Consolas", 12), text_color=MUTED
        )
        self._status_dot.grid(row=0, column=1, padx=(0, 4), pady=4)

        name_lbl = ctk.CTkLabel(
            self, text=m.name[:70], anchor="w",
            font=("Segoe UI", 10), text_color=TEXT
        )
        name_lbl.grid(row=0, column=2, sticky="w", padx=2, pady=4)

        self._status_lbl = ctk.CTkLabel(
            self, text="Pending", width=120, anchor="e",
            font=("Segoe UI", 9), text_color=MUTED
        )
        self._status_lbl.grid(row=0, column=3, padx=(4, 6), pady=4)

        self._prog = ctk.CTkProgressBar(self, height=3, mode="determinate")
        self._prog.set(0)

    def update_status(self, status: ModStatus, detail: str = "") -> None:
        color = STATUS_COLORS.get(status, MUTED)
        label = status.value
        if detail and status == ModStatus.DOWNLOADING:
            label = detail
        self._status_dot.configure(text_color=color)
        self._status_lbl.configure(text=label[:22], text_color=color)

        if status in (ModStatus.DOWNLOADING, ModStatus.INSTALLING):
            if status == ModStatus.INSTALLING:
                self._prog.set(0)
            if not self._prog.winfo_ismapped():
                self._prog.grid(row=1, column=0, columnspan=4, padx=6, pady=(0, 4), sticky="ew")
        elif self._prog.winfo_ismapped():
            self._prog.grid_forget()

    def update_progress(self, pct: float, kb: int, total_kb: int) -> None:
        self._prog.set(max(0.0, min(1.0, pct)))
        if total_kb:
            self._status_lbl.configure(text=f"{kb}/{total_kb} KB")
        else:
            self._status_lbl.configure(text=f"{kb} KB")

    def update_install_progress(self, pct: float, label: str) -> None:
        if not self._prog.winfo_ismapped():
            self._prog.grid(row=1, column=0, columnspan=4, padx=6, pady=(0, 4), sticky="ew")
        self._prog.set(max(0.0, min(1.0, pct)))
        self._status_lbl.configure(text=label[:22], text_color=WARNING)


# ---------------------------------------------------------------------------
# Log panel
# ---------------------------------------------------------------------------

class LogPanel(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color=BG, **kw)
        self._st = scrolledtext.ScrolledText(
            self, bg="#0a0a14", fg=TEXT, insertbackground=TEXT,
            font=("Consolas", 9), state="disabled", relief="flat", wrap="word"
        )
        self._st.pack(fill="both", expand=True, padx=2, pady=2)
        for tag, color in [("success", SUCCESS), ("error", ERROR_COL),
                           ("warning", WARNING), ("muted", MUTED), ("info", INFO)]:
            self._st.tag_config(tag, foreground=color)

    def log(self, msg: str, tag: str = "") -> None:
        self._st.configure(state="normal")
        self._st.insert("end", msg + "\n", tag or ())
        self._st.see("end")
        self._st.configure(state="disabled")

    def clear(self) -> None:
        self._st.configure(state="normal")
        self._st.delete("1.0", "end")
        self._st.configure(state="disabled")


# ---------------------------------------------------------------------------
# TSLPatcher banner
# ---------------------------------------------------------------------------

class PatcherBanner(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color="#3d1c00", corner_radius=0, **kw)
        self._label = ctk.CTkLabel(
            self,
            text="",
            text_color=WARNING,
            font=("Segoe UI", 11, "bold"),
            wraplength=900,
        )
        self._label.pack(pady=8, padx=16)

    def show(self, mod_name: str, game_path: str) -> None:
        self._label.configure(
            text=f"⚠  TSLPatcher is open for: {mod_name}\n"
                 f"   Paste the game path  ›  {game_path}  ‹  then click Install Mod and close the window."
        )
        self.pack(fill="x", before=self.master.winfo_children()[1])

    def hide(self) -> None:
        self.pack_forget()


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, conf: dict, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("560x340")
        self.resizable(False, False)
        self.grab_set()
        self._conf = conf
        self._on_save = on_save
        self._build()

    def _path_row(self, parent, label, key, row):
        ctk.CTkLabel(parent, text=label, anchor="w", width=130).grid(row=row, column=0, padx=8, pady=5, sticky="w")
        var = tk.StringVar(value=self._conf.get(key, ""))
        entry = ctk.CTkEntry(parent, textvariable=var, width=310)
        entry.grid(row=row, column=1, padx=4, pady=5)
        ctk.CTkButton(
            parent, text="Browse", width=68,
            command=lambda v=var: v.set(filedialog.askdirectory() or v.get())
        ).grid(row=row, column=2, padx=4, pady=5)
        return var

    def _build(self):
        f = ctk.CTkFrame(self, fg_color=PANEL)
        f.pack(fill="both", expand=True, padx=16, pady=16)
        f.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(f, text="Game Paths", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=3, padx=8, pady=(8, 4), sticky="w")
        self._k1 = self._path_row(f, "KOTOR 1 Path", "kotor1_path", 1)
        self._k2 = self._path_row(f, "KOTOR 2 Path", "kotor2_path", 2)
        self._dl = self._path_row(f, "Download Dir",  "download_dir",  3)

        ctk.CTkButton(f, text="Save & Close", command=self._save,
                      fg_color=HIGHLIGHT).grid(row=4, column=0, columnspan=3, pady=14)

    def _save(self):
        self._conf.update({
            "kotor1_path": self._k1.get(),
            "kotor2_path": self._k2.get(),
            "download_dir": self._dl.get(),
        })
        cfg.save(self._conf)
        self._on_save(self._conf)
        self.destroy()


# ---------------------------------------------------------------------------
# Login dialog
# ---------------------------------------------------------------------------

class LoginDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("DeadlyStream Login")
        self.geometry("380x240")
        self.resizable(False, False)
        self.grab_set()
        self.result: Optional[tuple[str, str]] = None

        ctk.CTkLabel(self, text="DeadlyStream Credentials",
                     font=("Segoe UI", 14, "bold")).pack(pady=(18, 8))

        saved_u, saved_p = DeadlyStreamClient.load_credentials()
        self._u = ctk.CTkEntry(self, placeholder_text="Username", width=290)
        self._u.pack(pady=4)
        if saved_u:
            self._u.insert(0, saved_u)

        self._p = ctk.CTkEntry(self, placeholder_text="Password", show="*", width=290)
        self._p.pack(pady=4)
        if saved_p:
            self._p.insert(0, saved_p)

        self._save_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="Save credentials", variable=self._save_var).pack(pady=4)
        ctk.CTkButton(self, text="Login", command=self._ok, fg_color=HIGHLIGHT).pack(pady=10)

    def _ok(self):
        u, p = self._u.get().strip(), self._p.get().strip()
        if not u or not p:
            messagebox.showerror("Error", "Username and password required.", parent=self)
            return
        if self._save_var.get():
            DeadlyStreamClient.save_credentials(u, p)
        self.result = (u, p)
        self.destroy()


# ---------------------------------------------------------------------------
# Readme / manual install dialog
# ---------------------------------------------------------------------------

class ReadmeDialog(ctk.CTkToplevel):
    def __init__(self, parent, title_text: str, body: str):
        super().__init__(parent)
        self.title(title_text)
        self.geometry("660x500")
        self.grab_set()
        st = scrolledtext.ScrolledText(self, bg="#0a0a14", fg=TEXT, font=("Consolas", 9), wrap="word")
        st.pack(fill="both", expand=True, padx=8, pady=8)
        st.insert("end", body)
        st.configure(state="disabled")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KOTOR Mod Installer")
        self.geometry("1200x800")
        self.minsize(900, 620)
        self.configure(fg_color=BG)

        self._conf = cfg.load()
        self._client = DeadlyStreamClient()
        self._pipeline: Optional[Pipeline] = None
        self._pipeline_mods: list[PipelineMod] = []
        self._rows: dict[str, ModRow] = {}           # file_id → row
        self._log_queue: queue.Queue = queue.Queue()
        self._ui_queue: queue.Queue = queue.Queue()   # thread→main UI updates
        self._selected_build = "k1_full"

        self._build_ui()
        self._start_queue_drain()
        self.after(300, self._try_auto_login)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color=ACCENT, height=56, corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="KOTOR Mod Installer",
                     font=("Segoe UI", 16, "bold"), text_color=TEXT).pack(side="left", padx=16)

        ctk.CTkButton(top, text="⚙ Settings", width=90, height=32,
                      fg_color=PANEL, command=self._open_settings).pack(side="right", padx=6, pady=10)

        self._login_btn = ctk.CTkButton(
            top, text="Login to DeadlyStream", width=190, height=32,
            fg_color=HIGHLIGHT, hover_color="#c0392b", command=self._do_login
        )
        self._login_btn.pack(side="right", padx=6, pady=10)

        # ── TSLPatcher banner (hidden initially) ──────────────────────
        self._patcher_banner = ctk.CTkFrame(self, fg_color="#3d1800", corner_radius=0, height=56)
        self._patcher_banner.pack_propagate(False)
        self._banner_label = ctk.CTkLabel(
            self._patcher_banner, text="", text_color=WARNING,
            font=("Segoe UI", 11, "bold"), wraplength=1100
        )
        self._banner_label.pack(expand=True)

        # ── Build selector row ────────────────────────────────────────
        sel_row = ctk.CTkFrame(self, fg_color=PANEL, height=48)
        sel_row.pack(fill="x")
        sel_row.pack_propagate(False)

        ctk.CTkLabel(sel_row, text="Build:", text_color=MUTED, font=("Segoe UI", 10)).pack(side="left", padx=(12, 4))
        self._build_menu = ctk.CTkOptionMenu(
            sel_row,
            values=list(BUILD_LABELS.values()),
            command=self._on_build_selected,
            width=240, height=30,
        )
        self._build_menu.set(BUILD_LABELS["k1_full"])
        self._build_menu.pack(side="left", padx=4, pady=8)

        ctk.CTkButton(
            sel_row, text="Load Mod List", width=120, height=30,
            fg_color=PANEL2, command=self._load_build
        ).pack(side="left", padx=8)

        self._count_lbl = ctk.CTkLabel(sel_row, text="", text_color=MUTED, font=("Consolas", 9))
        self._count_lbl.pack(side="left", padx=6)

        # overall progress
        self._overall_prog = ctk.CTkProgressBar(sel_row, width=200, height=8, mode="determinate")
        self._overall_prog.set(0)
        self._overall_prog.pack(side="right", padx=(4, 8))
        ctk.CTkLabel(sel_row, text="Overall:", text_color=MUTED, font=("Segoe UI", 9)).pack(side="right")

        # ── Main content ─────────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color=BG)
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        # Left: mod queue
        left = ctk.CTkFrame(content, fg_color=BG)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._scroll = ctk.CTkScrollableFrame(left, fg_color=BG, label_text="")
        self._scroll.pack(fill="both", expand=True, padx=(8, 4), pady=(4, 0))
        self._scroll.grid_columnconfigure(0, weight=1)

        # Right: log
        right = ctk.CTkFrame(content, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Log", font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, padx=8, pady=(8, 2), sticky="w")
        self._log_panel = LogPanel(right)
        self._log_panel.grid(row=1, column=0, sticky="nsew", padx=(4, 8), pady=(0, 4))
        ctk.CTkButton(right, text="Clear", width=60, height=22,
                      fg_color=PANEL, command=self._log_panel.clear
                      ).grid(row=2, column=0, pady=(0, 6))

        # ── Bottom action bar ─────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color=PANEL, height=52, corner_radius=0)
        bot.pack(fill="x", side="bottom")
        bot.pack_propagate(False)

        self._install_btn = ctk.CTkButton(
            bot, text="▶  Download & Install All", width=220, height=36,
            fg_color=HIGHLIGHT, hover_color="#c0392b", font=("Segoe UI", 12, "bold"),
            command=self._start_pipeline
        )
        self._install_btn.pack(side="left", padx=12, pady=8)

        self._pause_btn = ctk.CTkButton(
            bot, text="⏸ Pause", width=90, height=36,
            fg_color=ACCENT, state="disabled", command=self._toggle_pause
        )
        self._pause_btn.pack(side="left", padx=4, pady=8)

        self._stop_btn = ctk.CTkButton(
            bot, text="■ Stop", width=80, height=36,
            fg_color="#444", state="disabled", command=self._stop_pipeline
        )
        self._stop_btn.pack(side="left", padx=4, pady=8)

        self._unattended_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bot, text="Unattended (never prompt)", variable=self._unattended_var,
            font=("Segoe UI", 9), checkbox_width=18, checkbox_height=18,
        ).pack(side="left", padx=10)

        self._status_lbl = ctk.CTkLabel(bot, text="Load a mod list to begin.",
                                        text_color=MUTED, font=("Consolas", 9))
        self._status_lbl.pack(side="left", padx=12)

        # HoloPatcher shim availability indicator
        self._shim_lbl = ctk.CTkLabel(bot, text="", text_color=MUTED, font=("Consolas", 9))
        self._shim_lbl.pack(side="right", padx=12)
        self._refresh_shim_status()

    # ------------------------------------------------------------------
    # Queue drain (thread-safe UI updates)
    # ------------------------------------------------------------------

    def _start_queue_drain(self):
        def drain():
            while True:
                try:
                    fn = self._ui_queue.get_nowait()
                    fn()
                except queue.Empty:
                    break
            while True:
                try:
                    msg, tag = self._log_queue.get_nowait()
                    self._log_panel.log(msg, tag)
                except queue.Empty:
                    break
        self.after(80, lambda: (drain(), self._start_queue_drain()))

    def _ui(self, fn):
        """Schedule fn() on the main thread."""
        self._ui_queue.put(fn)

    def log(self, msg: str, tag: str = "") -> None:
        self._log_queue.put((msg, tag))

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def _try_auto_login(self):
        u, p = DeadlyStreamClient.load_credentials()
        if u and p:
            threading.Thread(target=self._login_thread, args=(u, p), daemon=True).start()

    def _do_login(self):
        dlg = LoginDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            threading.Thread(target=self._login_thread, args=dlg.result, daemon=True).start()

    def _login_thread(self, username: str, password: str):
        self.log(f"Logging in as {username}...")
        try:
            self._client.login(username, password)
            self.log(f"Logged in as {username}.", "success")
            self._ui(lambda u=username: self._login_btn.configure(
                text=f"✓ {u}", fg_color="#1a6b3a"))
        except AuthError as e:
            self.log(f"Login failed: {e}", "error")

    # ------------------------------------------------------------------
    # Build selection & loading
    # ------------------------------------------------------------------

    def _on_build_selected(self, label: str):
        for key, lbl in BUILD_LABELS.items():
            if lbl == label:
                self._selected_build = key
                break

    def _load_build(self):
        build = self._selected_build
        self.log(f"Loading {BUILD_LABELS[build]}...")
        self._count_lbl.configure(text="Loading...")
        threading.Thread(target=self._scrape_thread, args=(build,), daemon=True).start()

    def _scrape_thread(self, build_key: str):
        try:
            mods = scrape_build(build_key)
            self._ui(lambda m=mods, b=build_key: self._populate_queue(m, b))
            self.log(f"Loaded {len(mods)} mods in install order.", "success")
        except Exception as e:
            self.log(f"Scrape error: {e}", "error")
            self._ui(lambda: self._count_lbl.configure(text="Load failed."))

    def _populate_queue(self, mods: list[BuildMod], build_key: str):
        # Clear existing
        for w in self._scroll.winfo_children():
            w.destroy()
        self._rows.clear()
        self._pipeline_mods = [PipelineMod(m) for m in mods]

        for pm in self._pipeline_mods:
            row = ModRow(self._scroll, pm)
            row.grid(sticky="ew", padx=4, pady=2)
            self._rows[pm.build_mod.file_id] = row

        total = len(mods)
        self._count_lbl.configure(text=f"{total} mods  |  {BUILD_LABELS[build_key]}")
        self._overall_prog.set(0)
        self._status_lbl.configure(text=f"Ready. {total} mods queued.")

    # ------------------------------------------------------------------
    # Pipeline start / stop / pause
    # ------------------------------------------------------------------

    def _get_game_path(self, build_key: str) -> Optional[Path]:
        game = BUILD_GAME[build_key]
        key = "kotor1_path" if game == "KOTOR1" else "kotor2_path"
        p = self._conf.get(key, "")
        return Path(p) if p else None

    def _start_pipeline(self):
        if not self._pipeline_mods:
            messagebox.showinfo("No mods", "Load a mod list first.")
            return
        if not self._client._logged_in:
            messagebox.showwarning("Not logged in", "Please log in to DeadlyStream first.")
            return

        game_path = self._get_game_path(self._selected_build)
        if not game_path or not game_path.exists():
            game = BUILD_GAME[self._selected_build]
            p = filedialog.askdirectory(title=f"Select {game} installation folder")
            if not p:
                return
            game_path = Path(p)
            key = "kotor1_path" if game == "KOTOR1" else "kotor2_path"
            self._conf[key] = p
            cfg.save(self._conf)

        dl_dir = Path(self._conf.get("download_dir", str(Path.home() / "Downloads" / "KOTOR_Mods")))
        mods = [pm.build_mod for pm in self._pipeline_mods]

        self._pipeline = Pipeline(
            mods=mods,
            game_path=game_path,
            download_dir=dl_dir,
            client=self._client,
            on_status=self._on_mod_status,
            on_log=self._on_pipeline_log,
            on_progress=self._on_mod_progress,
            on_install_progress=self._on_install_progress,
            auto_unattended=self._unattended_var.get(),
        )

        # Reset all rows to pending
        for pm in self._pipeline_mods:
            pm.status = ModStatus.PENDING
            row = self._rows.get(pm.build_mod.file_id)
            if row:
                self._ui(lambda r=row: r.update_status(ModStatus.PENDING))

        self._install_btn.configure(state="disabled")
        self._pause_btn.configure(state="normal")
        self._stop_btn.configure(state="normal")
        self._status_lbl.configure(text="Installing...")
        self.log(f"Starting installation: {len(mods)} mods → {game_path}", "info")

        self._pipeline.start()
        self._monitor_pipeline()

    def _monitor_pipeline(self):
        if self._pipeline and self._pipeline.is_running:
            done = sum(1 for pm in self._pipeline.mods if pm.status in (ModStatus.DONE, ModStatus.SKIPPED, ModStatus.ERROR))
            total = len(self._pipeline.mods)
            self._overall_prog.set(done / total if total else 0)
            self.after(500, self._monitor_pipeline)
        else:
            self._on_pipeline_done()

    def _on_pipeline_done(self):
        mods = self._pipeline.mods if self._pipeline else self._pipeline_mods
        done = sum(1 for pm in mods if pm.status == ModStatus.DONE)
        errors = sum(1 for pm in mods if pm.status == ModStatus.ERROR)
        total = len(mods)
        self._overall_prog.set(1.0)
        self._install_btn.configure(state="normal")
        self._pause_btn.configure(state="disabled", text="⏸ Pause")
        self._stop_btn.configure(state="disabled")
        self._patcher_banner_hide()
        msg = f"Complete: {done}/{total} installed"
        if errors:
            msg += f", {errors} error(s)"
        self._status_lbl.configure(text=msg)
        self.log(f"\n{'='*50}", "muted")
        self.log(msg, "success" if not errors else "warning")

    def _toggle_pause(self):
        if not self._pipeline:
            return
        if self._pipeline._pause_event.is_set():
            self._pipeline.pause()
            self._pause_btn.configure(text="▶ Resume")
            self._status_lbl.configure(text="Paused.")
        else:
            self._pipeline.resume()
            self._pause_btn.configure(text="⏸ Pause")
            self._status_lbl.configure(text="Resuming...")

    def _stop_pipeline(self):
        if self._pipeline:
            self._pipeline.stop()
            self._status_lbl.configure(text="Stopping...")

    # ------------------------------------------------------------------
    # Pipeline callbacks (called from background thread)
    # ------------------------------------------------------------------

    def _on_mod_status(self, file_id: str, status: ModStatus, detail: str) -> None:
        def _update():
            row = self._rows.get(file_id)
            if row:
                row.update_status(status, detail)
            # TSLPatcher banner
            if status == ModStatus.WAITING_PATCHER:
                pm = next((p for p in self._pipeline_mods if p.build_mod.file_id == file_id), None)
                name = pm.build_mod.name if pm else file_id
                game = self._get_game_path(self._selected_build) or "?"
                self._patcher_banner_show(name, str(game))
            elif status in (ModStatus.DONE, ModStatus.ERROR):
                self._patcher_banner_hide()
            # Scroll active row into view
            if status in (ModStatus.DOWNLOADING, ModStatus.INSTALLING, ModStatus.WAITING_PATCHER):
                self._scroll_to(file_id)
        self._ui(_update)

    def _on_mod_progress(self, file_id: str, pct: float, kb: int, total_kb: int) -> None:
        def _update():
            row = self._rows.get(file_id)
            if row:
                row.update_progress(pct, kb, total_kb)
        self._ui(_update)

    def _on_install_progress(self, file_id: str, pct: float, label: str) -> None:
        def _update():
            row = self._rows.get(file_id)
            if row:
                row.update_install_progress(pct, label)
        self._ui(_update)

    def _on_pipeline_log(self, msg: str, tag: str) -> None:
        self.log(msg, tag)

    # ------------------------------------------------------------------
    # HoloPatcher shim status
    # ------------------------------------------------------------------

    def _refresh_shim_status(self) -> None:
        try:
            from installer.config_loader import find_system_holopatcher
            holo = find_system_holopatcher()
        except Exception:
            holo = None
        if holo:
            self._shim_lbl.configure(
                text=f"⚡ Headless patcher: {holo.name}", text_color=SUCCESS)
        else:
            self._shim_lbl.configure(
                text="⚠ No HoloPatcher shim (TSLPatcher will be automated/GUI)",
                text_color=WARNING)

    # ------------------------------------------------------------------
    # TSLPatcher banner
    # ------------------------------------------------------------------

    def _patcher_banner_show(self, mod_name: str, game_path: str) -> None:
        txt = (
            f"⚠  TSLPatcher is open for: {mod_name}\n"
            f"   Game path: {game_path}  (already on clipboard)\n"
            f"   Paste it into the patcher, click Install Mod, then close the window."
        )
        self._banner_label.configure(text=txt)
        if not self._patcher_banner.winfo_ismapped():
            self._patcher_banner.pack(fill="x", after=self.winfo_children()[0])

    def _patcher_banner_hide(self) -> None:
        if self._patcher_banner.winfo_ismapped():
            self._patcher_banner.pack_forget()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _scroll_to(self, file_id: str) -> None:
        row = self._rows.get(file_id)
        if row:
            try:
                self._scroll._parent_canvas.yview_moveto(
                    row.winfo_y() / max(1, self._scroll._parent_frame.winfo_height())
                )
            except Exception:
                pass

    def _open_settings(self):
        SettingsDialog(self, self._conf, on_save=lambda c: setattr(self, "_conf", c))
