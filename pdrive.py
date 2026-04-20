#!/usr/bin/env python3
"""rclone sync GUI — tkinter front end with live log pane and progress bar."""

import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from rclone_common import (
    copy_args,
    get_remotes,
    new_log_path,
    parse_progress,
    rclone_cmd,
    rclone_installed,
    valid_batch,
)


# ── Saved connections ─────────────────────────────────────────────────────────

SAVES_FILE = Path.home() / ".pdrive_saves.json"


def load_saves():
    try:
        if SAVES_FILE.exists():
            return json.loads(SAVES_FILE.read_text())
    except Exception:
        pass
    return []


def upsert_save(entry):
    saves = [s for s in load_saves() if s["name"] != entry["name"]]
    saves.append(entry)
    SAVES_FILE.write_text(json.dumps(saves, indent=2))


def delete_save(name):
    saves = [s for s in load_saves() if s["name"] != name]
    SAVES_FILE.write_text(json.dumps(saves, indent=2))


# ── rclone helpers ────────────────────────────────────────────────────────────

def rclone_capture(*args):
    r = subprocess.run(["rclone"] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ── Sync runner ───────────────────────────────────────────────────────────────

class SyncRunner:
    """Drives the rclone copy loop. Pushes updates to the run window via callbacks."""

    def __init__(self, src, dst, batch, dry_run, auto_batch, ui):
        self.src, self.dst = src, dst
        self.batch = batch
        self.dry_run = dry_run
        self.auto_batch = auto_batch
        self.ui = ui                # RunWindow callbacks
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _spawn(self, args):
        self.proc = subprocess.Popen(
            rclone_cmd(*args),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in self.proc.stdout:
            if self.cancelled:
                break
            line = line.rstrip()
            self.ui.log(line)
            prog = parse_progress(line)
            if prog:
                self.ui.progress(prog[2], f"{prog[0]} / {prog[1]}")
        self.proc.wait()
        return self.proc.returncode

    def run(self):
        log_file = new_log_path()
        self.ui.log(f"── {self.src}  →  {self.dst}")
        self.ui.log(f"── batch={self.batch}  auto={'yes' if self.auto_batch else 'one run'}")
        self.ui.log(f"── log file: {log_file}")

        if self.dry_run:
            self.ui.log("\n── Dry run (no files will be copied) ──")
            self._spawn(["copy", self.src, self.dst,
                         "--dry-run", "--stats", "2s", "--stats-one-line",
                         "--ignore-existing"])
            self.ui.done("Dry run complete. Uncheck 'Dry run first' to transfer for real.")
            return

        run_n = 0
        while not self.cancelled:
            run_n += 1
            self.ui.log(f"\n── Batch {run_n} ──")
            self.ui.progress(0, "starting…")
            t0 = time.time()
            rc = self._spawn(copy_args(self.src, self.dst, self.batch, log_file))
            elapsed = int(time.time() - t0)
            self.ui.log(f"\nBatch {run_n} done in {elapsed//60}m {elapsed%60}s  (exit {rc})")

            if self.cancelled:
                self.ui.done("Cancelled.")
                return
            if rc == 0:
                self.ui.progress(100, "complete")
                self.ui.done("✓ All done — nothing left to transfer.")
                return
            if not self.auto_batch:
                self.ui.done("One batch complete. Press Start again to continue.")
                return
            if rc == 9:                  # max-transfer hit; more work to do
                self.ui.log("Pausing 3s before next batch…")
                time.sleep(3)
                continue
            self.ui.done(f"Error: rclone exited {rc}. See log: {log_file}")
            return


# ── Run window (live log + progress + cancel) ────────────────────────────────

class RunWindow(tk.Toplevel):
    def __init__(self, parent, src, dst, batch, dry_run, auto_batch):
        super().__init__(parent)
        self.title("rclone Sync — running")
        self.minsize(680, 420)
        self._build()
        self.runner = SyncRunner(src, dst, batch, dry_run, auto_batch, self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self.runner.run, daemon=True).start()

    def _build(self):
        bar = tk.Frame(self, padx=10, pady=8)
        bar.pack(fill="x")
        self.pct_lbl = tk.Label(bar, text="0%", width=5, anchor="w",
                                font=("TkFixedFont", 10))
        self.pct_lbl.pack(side="left")
        self.bar = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.bar.pack(side="left", fill="x", expand=True, padx=8)
        self.detail_lbl = tk.Label(bar, text="", width=22, anchor="e",
                                   font=("TkFixedFont", 9), fg="#555")
        self.detail_lbl.pack(side="left")
        self.cancel_btn = tk.Button(bar, text="Cancel", fg="#c0392b",
                                    command=self._cancel)
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.txt = scrolledtext.ScrolledText(self, font=("TkFixedFont", 10),
                                             wrap="none", padx=8, pady=6)
        self.txt.pack(fill="both", expand=True)
        self.txt.config(state="disabled")

    # callbacks invoked from worker thread; marshal to the Tk thread
    def log(self, line):
        self.after(0, self._append_log, line)

    def progress(self, pct, detail=""):
        self.after(0, self._set_progress, pct, detail)

    def done(self, message):
        self.after(0, self._on_done, message)

    def _append_log(self, line):
        self.txt.config(state="normal")
        self.txt.insert("end", line + "\n")
        self.txt.see("end")
        self.txt.config(state="disabled")

    def _set_progress(self, pct, detail):
        self.bar["value"] = pct
        self.pct_lbl.config(text=f"{pct}%")
        self.detail_lbl.config(text=detail)

    def _on_done(self, message):
        self._append_log("\n" + message)
        self.cancel_btn.config(text="Close", fg="black", command=self.destroy)

    def _cancel(self):
        if self.runner.proc and self.runner.proc.poll() is None:
            self.runner.cancel()
            self._append_log("\nCancelling…")
        else:
            self.destroy()

    def _on_close(self):
        if self.runner.proc and self.runner.proc.poll() is None:
            if not messagebox.askyesno("Cancel sync?",
                                       "A sync is still running. Cancel and close?",
                                       parent=self):
                return
            self.runner.cancel()
        self.destroy()


# ── Remote browser ────────────────────────────────────────────────────────────

class RemoteBrowser(tk.Toplevel):
    """Modal dialog for navigating and selecting a remote folder."""

    def __init__(self, parent, remote):
        super().__init__(parent)
        self.title(f"Browse  {remote}:")
        self.remote = remote
        self.path = ""
        self.result = None
        self.items = []
        self.resizable(True, True)
        self.minsize(460, 380)
        self._build()
        self.transient(parent)
        self.grab_set()
        self._load()
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    def _build(self):
        top = tk.Frame(self, pady=6, padx=10)
        top.pack(fill="x")
        self.path_lbl = tk.Label(top, text="", anchor="w", font=("TkFixedFont", 10))
        self.path_lbl.pack(side="left", fill="x", expand=True)

        mid = tk.Frame(self)
        mid.pack(fill="both", expand=True, padx=10)
        sb = tk.Scrollbar(mid)
        sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(mid, yscrollcommand=sb.set, font=("TkFixedFont", 10),
                             activestyle="dotbox", selectmode="browse")
        self.lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind("<Double-Button-1>", lambda _: self._open())
        self.lb.bind("<Return>",          lambda _: self._open())
        self.lb.bind("<BackSpace>",       lambda _: self._back())

        bot = tk.Frame(self, pady=8, padx=10)
        bot.pack(fill="x")
        tk.Button(bot, text="← Back",  width=9,  command=self._back).pack(side="left", padx=3)
        tk.Button(bot, text="Open →",  width=9,  command=self._open).pack(side="left", padx=3)
        tk.Button(bot, text="Select this folder", width=20,
                  bg="#1a73e8", fg="white", command=self._select).pack(side="right", padx=3)

    def _load(self):
        self.path_lbl.config(text=f"  {self.remote}:/{self.path or ''}")
        self.lb.delete(0, "end")
        self.lb.insert("end", "  loading…")
        self.lb.config(state="disabled")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        rc, out = rclone_capture("lsjson", f"{self.remote}:{self.path}",
                                 "--no-modtime", "--no-mimetype")
        try:
            self.items = [i for i in json.loads(out) if i.get("IsDir")] if rc == 0 else []
        except Exception:
            self.items = []
        self.after(0, self._populate)

    def _populate(self):
        self.lb.config(state="normal")
        self.lb.delete(0, "end")
        if not self.items:
            self.lb.insert("end", "  (no subfolders)")
        for item in self.items:
            self.lb.insert("end", f"  {item['Name']}/")

    def _selected_item(self):
        sel = self.lb.curselection()
        return self.items[sel[0]] if sel and sel[0] < len(self.items) else None

    def _open(self):
        item = self._selected_item()
        if item:
            self.path = (self.path.rstrip("/") + "/" + item["Name"]).lstrip("/")
            self._load()

    def _back(self):
        if self.path:
            self.path = "/".join(self.path.rstrip("/").split("/")[:-1])
            self._load()

    def _select(self):
        self.result = self.path
        self.destroy()


# ── Sync dialog ───────────────────────────────────────────────────────────────

class SyncDialog(tk.Toplevel):
    """Configure and launch a push or pull. Accepts optional prefill dict."""

    def __init__(self, parent, remotes, direction, prefill=None):
        super().__init__(parent)
        self.title("Upload  (local → remote)" if direction == "push"
                   else "Download  (remote → local)")
        self.direction = direction
        self.remotes   = remotes
        self._remote_path = None
        self.resizable(False, False)
        self._build()
        if prefill:
            self._apply_prefill(prefill)
        self.transient(parent)
        self.grab_set()
        self.bind("<Return>", lambda _: self._start())
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build(self):
        f = tk.Frame(self, padx=16, pady=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        tk.Label(f, text="Remote:", anchor="e", width=20).grid(
            row=0, column=0, sticky="e", pady=5, padx=(0, 8))
        self.remote_var = tk.StringVar(value=self.remotes[0] if self.remotes else "")
        ttk.Combobox(f, textvariable=self.remote_var, values=self.remotes,
                     state="readonly", width=30).grid(row=0, column=1, columnspan=2,
                                                       sticky="w", pady=5)

        if self.direction == "push":
            self._local_row(f, 1, "Local source:")
            self._remote_row(f, 2, "Remote destination:")
        else:
            self._remote_row(f, 1, "Remote source:")
            self._local_row(f, 2, "Local destination:")

        tk.Label(f, text="Batch size:", anchor="e", width=20).grid(
            row=3, column=0, sticky="e", pady=5, padx=(0, 8))
        self.batch_var = tk.StringVar(value="2G")
        tk.Entry(f, textvariable=self.batch_var, width=10).grid(
            row=3, column=1, sticky="w", pady=5)
        tk.Label(f, text="e.g. 500M · 2G · 10G", fg="gray").grid(
            row=3, column=2, sticky="w")

        self.dry_var  = tk.BooleanVar(value=True)
        self.auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="Dry run first  (safe preview — no files copied)",
                       variable=self.dry_var).grid(
            row=4, column=1, columnspan=2, sticky="w", pady=2)
        tk.Checkbutton(f, text="Auto-batch until fully done  (set & forget)",
                       variable=self.auto_var).grid(
            row=5, column=1, columnspan=2, sticky="w", pady=2)

        sf = tk.LabelFrame(f, text="Save this connection", padx=8, pady=6)
        sf.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 4))
        tk.Label(sf, text="Name:").pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.name_var, width=26).pack(side="left", padx=6)
        tk.Button(sf, text="Save", command=self._save).pack(side="left")

        tk.Button(f, text="  Start  ", bg="#1a73e8", fg="white",
                  font=("TkDefaultFont", 11, "bold"),
                  command=self._start).grid(row=7, column=1, pady=(12, 4), sticky="w")

    def _local_row(self, f, row, label):
        tk.Label(f, text=label, anchor="e", width=20).grid(
            row=row, column=0, sticky="e", pady=5, padx=(0, 8))
        self.local_var = tk.StringVar()
        tk.Entry(f, textvariable=self.local_var, width=31).grid(
            row=row, column=1, sticky="w", pady=5)
        tk.Button(f, text="Browse…", command=self._pick_local).grid(
            row=row, column=2, padx=4, pady=5)

    def _remote_row(self, f, row, label):
        tk.Label(f, text=label, anchor="e", width=20).grid(
            row=row, column=0, sticky="e", pady=5, padx=(0, 8))
        self.remote_lbl_var = tk.StringVar(value="(click Browse…)")
        tk.Label(f, textvariable=self.remote_lbl_var, fg="#1a73e8",
                 anchor="w", width=31).grid(row=row, column=1, sticky="w", pady=5)
        tk.Button(f, text="Browse…", command=self._pick_remote).grid(
            row=row, column=2, padx=4, pady=5)

    # ── actions ───────────────────────────────────────────────────────────────

    def _pick_local(self):
        path = filedialog.askdirectory(parent=self, title="Select folder")
        if path:
            self.local_var.set(path)

    def _pick_remote(self):
        remote = self.remote_var.get()
        if not remote:
            messagebox.showwarning("Select remote", "Choose a remote first.", parent=self)
            return
        browser = RemoteBrowser(self, remote)
        if browser.result is not None:
            self._remote_path = browser.result
            label = f"{remote}:/{browser.result}" if browser.result else f"{remote}:  (root)"
            self.remote_lbl_var.set(label)

    def _apply_prefill(self, p):
        self.remote_var.set(p["remote"])
        self.local_var.set(p["local"])
        self._remote_path = p["remote_path"]
        label = f"{p['remote']}:/{p['remote_path']}" if p["remote_path"] else f"{p['remote']}:  (root)"
        self.remote_lbl_var.set(label)
        self.batch_var.set(p.get("batch", "2G"))
        self.name_var.set(p.get("name", ""))
        self.auto_var.set(p.get("auto_batch", True))

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a name for this connection.", parent=self)
            return
        local = self.local_var.get().strip()
        if not local or self._remote_path is None:
            messagebox.showwarning("Incomplete", "Fill in all paths before saving.", parent=self)
            return
        batch = self.batch_var.get().strip() or "2G"
        if not valid_batch(batch):
            messagebox.showwarning("Bad batch size",
                                   "Use a number with optional K/M/G/T suffix (e.g. 500M, 2G).",
                                   parent=self)
            return
        upsert_save({
            "name":       name,
            "direction":  self.direction,
            "remote":     self.remote_var.get(),
            "remote_path": self._remote_path,
            "local":      local,
            "batch":      batch,
            "auto_batch": self.auto_var.get(),
        })
        messagebox.showinfo("Saved", f"'{name}' saved.", parent=self)

    def _start(self):
        remote = self.remote_var.get()
        local  = self.local_var.get().strip()
        batch  = self.batch_var.get().strip() or "2G"
        if not remote:
            messagebox.showwarning("Missing", "Select a remote.", parent=self); return
        if not local:
            messagebox.showwarning("Missing", "Select a local folder.", parent=self); return
        if self._remote_path is None:
            messagebox.showwarning("Missing", "Browse and select a remote folder.", parent=self); return
        if not valid_batch(batch):
            messagebox.showwarning("Bad batch size",
                                   "Use a number with optional K/M/G/T suffix (e.g. 500M, 2G).",
                                   parent=self)
            return

        remote_full = f"{remote}:{self._remote_path}" if self._remote_path else f"{remote}:"
        src, dst = (local, remote_full) if self.direction == "push" else (remote_full, local)
        parent = self.master
        self.destroy()
        RunWindow(parent, src, dst, batch, self.dry_var.get(), self.auto_var.get())


# ── Status window ─────────────────────────────────────────────────────────────

class StatusWindow(tk.Toplevel):
    def __init__(self, parent, remotes):
        super().__init__(parent)
        self.title("Connection Status")
        self.resizable(True, True)
        self.minsize(440, 200)
        txt = tk.Text(self, font=("TkFixedFont", 10), padx=10, pady=8, wrap="none")
        sb  = tk.Scrollbar(self, command=txt.yview)
        txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        txt.insert("end", "Checking remotes…\n")
        txt.config(state="disabled")
        self.transient(parent)
        threading.Thread(target=self._fetch, args=(txt, remotes), daemon=True).start()

    def _fetch(self, txt, remotes):
        lines = []
        for r in remotes:
            lines.append(f"\n{r}:")
            rc, out = rclone_capture("about", f"{r}:")
            if rc == 0:
                lines += [f"  {l}" for l in out.splitlines()]
            else:
                rc2, _ = rclone_capture("lsd", f"{r}:", "--max-depth", "0")
                lines.append(f"  {'Connected ✓' if rc2 == 0 else 'Not reachable ✗'}")
        self.after(0, lambda: self._show(txt, "\n".join(lines)))

    def _show(self, txt, text):
        txt.config(state="normal")
        txt.delete("1.0", "end")
        txt.insert("end", text)
        txt.config(state="disabled")


# ── Main window ───────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("rclone Sync")
        self.resizable(False, False)
        self._build()
        self.remotes = []
        self.after(100, self._load_remotes)

    def _build(self):
        hdr = tk.Frame(self, bg="#1a1a2e", pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="rclone Sync", font=("TkDefaultFont", 16, "bold"),
                 bg="#1a1a2e", fg="white").pack()
        tk.Label(hdr, text="set & forget batched sync", font=("TkDefaultFont", 9),
                 bg="#1a1a2e", fg="#888").pack()

        body = tk.Frame(self, padx=24, pady=16)
        body.pack(fill="x")
        btn = dict(width=28, height=2, font=("TkDefaultFont", 11), cursor="hand2")
        tk.Button(body, text="⬆  Upload  (local → remote)",
                  bg="#1a73e8", fg="white",
                  command=lambda: self._open_sync("push"), **btn).pack(pady=4)
        tk.Button(body, text="⬇  Download  (remote → local)",
                  bg="#0f9d58", fg="white",
                  command=lambda: self._open_sync("pull"), **btn).pack(pady=4)
        tk.Button(body, text="◎  Connection Status",
                  bg="#444", fg="white",
                  command=self._open_status, **btn).pack(pady=4)

        sep = tk.Frame(self, height=1, bg="#ddd")
        sep.pack(fill="x", padx=16)
        tk.Label(self, text="SAVED CONNECTIONS",
                 font=("TkDefaultFont", 8, "bold"), fg="#888").pack(pady=(10, 2))
        self.saves_frame = tk.Frame(self, padx=16)
        self.saves_frame.pack(fill="x", pady=(0, 8))
        self._refresh_saves()

        self.status_lbl = tk.Label(self, text="Loading remotes…",
                                   fg="gray", font=("TkDefaultFont", 9), pady=8)
        self.status_lbl.pack()

    # ── saved connections ─────────────────────────────────────────────────────

    def _refresh_saves(self):
        for w in self.saves_frame.winfo_children():
            w.destroy()
        saves = load_saves()
        if not saves:
            tk.Label(self.saves_frame, text="None yet — fill in a sync dialog and hit Save",
                     fg="#aaa", font=("TkDefaultFont", 9)).pack(pady=4)
            return
        for s in saves:
            icon = "⬆" if s["direction"] == "push" else "⬇"
            row = tk.Frame(self.saves_frame)
            row.pack(fill="x", pady=2)
            tk.Button(row, text=f"{icon}  {s['name']}", anchor="w",
                      relief="groove", cursor="hand2",
                      command=lambda s=s: self._open_sync(s["direction"], prefill=s)
                      ).pack(side="left", fill="x", expand=True, ipady=3)
            tk.Button(row, text="×", fg="#c0392b", width=3, cursor="hand2",
                      command=lambda n=s["name"]: self._del_save(n)
                      ).pack(side="right", padx=(4, 0))

    def _del_save(self, name):
        if messagebox.askyesno("Delete", f"Delete '{name}'?", parent=self):
            delete_save(name)
            self._refresh_saves()

    # ── navigation ────────────────────────────────────────────────────────────

    def _load_remotes(self):
        threading.Thread(target=lambda: self.after(
            0, self._set_remotes, get_remotes()), daemon=True).start()

    def _set_remotes(self, remotes):
        self.remotes = remotes
        if remotes:
            self.status_lbl.config(text=f"Remotes: {', '.join(remotes)}", fg="#0f9d58")
        else:
            self.status_lbl.config(text="No remotes — run: rclone config", fg="#c0392b")

    def _open_sync(self, direction, prefill=None):
        if not self.remotes:
            messagebox.showinfo("No remotes", "No rclone remotes configured.\nRun: rclone config")
            return
        SyncDialog(self, self.remotes, direction, prefill=prefill)
        self._refresh_saves()

    def _open_status(self):
        if not self.remotes:
            messagebox.showinfo("No remotes", "No rclone remotes configured.\nRun: rclone config")
            return
        StatusWindow(self, self.remotes)


def main():
    if not rclone_installed():
        try:
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("rclone not found",
                                 "rclone is not installed or not on PATH.\n"
                                 "Install from https://rclone.org/install/")
        except tk.TclError:
            print("rclone is not installed or not on PATH.", file=sys.stderr)
        sys.exit(1)
    App().mainloop()


if __name__ == "__main__":
    main()
