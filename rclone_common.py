"""Shared helpers for the GUI and CLI rclone wrappers.

Keeps batch flags, log paths, and parsing in one place so both front ends
behave the same and you only have to tune things once.
"""

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".cache" / "simple-rclone"
BATCH_RE = re.compile(r"^\d+(\.\d+)?\s*[KMGTkmgt]?$")
PROGRESS_RE = re.compile(
    r"Transferred:\s+([\d.]+\s*\S+)\s*/\s*([\d.]+\s*\S+),\s*(\d+)%"
)

_STDBUF = shutil.which("stdbuf")


def rclone_installed():
    return shutil.which("rclone") is not None


def valid_batch(s):
    return bool(BATCH_RE.match((s or "").strip()))


def new_log_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return LOG_DIR / f"rclone-{stamp}.log"


def rclone_cmd(*args):
    """Wrap with stdbuf so progress lines flush in real time."""
    base = ([_STDBUF, "-oL", "-eL"] if _STDBUF else []) + ["rclone"]
    return base + list(args)


def get_remotes():
    try:
        r = subprocess.run(["rclone", "listremotes"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    return [line.rstrip(":") for line in r.stdout.splitlines() if line.strip()]


def copy_args(src, dst, batch, log_file=None):
    """Flag set used by every batch copy.

    Exit codes worth knowing:
      0 — finished, nothing more to transfer
      9 — --max-transfer limit hit (more work remains)
    """
    args = [
        "copy", src, dst,
        "--stats", "2s",
        "--stats-one-line",
        "--transfers", "4",
        "--checkers", "8",
        "--ignore-existing",
        "--max-transfer", batch,
        "--fast-list",
        "--retries", "3",
        "--low-level-retries", "10",
        "--retries-sleep", "10s",
        "--drive-pacer-min-sleep", "10ms",
        "--drive-pacer-burst", "200",
    ]
    if log_file:
        args += ["--log-file", str(log_file), "--log-level", "INFO"]
    return args


def parse_progress(line):
    """Return (done_str, total_str, pct) or None."""
    m = PROGRESS_RE.search(line)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))
