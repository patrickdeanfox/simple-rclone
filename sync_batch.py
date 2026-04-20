#!/usr/bin/env python3
"""Interactive rclone batch sync — loops until everything is transferred."""

import subprocess
import sys
import time

from rclone_common import (
    copy_args,
    get_remotes,
    new_log_path,
    rclone_cmd,
    rclone_installed,
    valid_batch,
)


def run(cmd):
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(line.rstrip())
    proc.wait()
    return proc.returncode


def prompt_batch():
    while True:
        s = input("\nBatch size per run (e.g. 1G, 500M, 5G) [default: 2G]: ").strip() or "2G"
        if valid_batch(s):
            return s
        print("Use a number with optional K/M/G/T suffix.")


def main():
    if not rclone_installed():
        print("rclone is not installed or not on PATH. See https://rclone.org/install/")
        sys.exit(1)

    print("=" * 50)
    print("  rclone Batch Sync")
    print("=" * 50)

    remotes = get_remotes()
    if not remotes:
        print("No rclone remotes found. Run 'rclone config' first.")
        sys.exit(1)

    print("\nAvailable remotes:")
    for i, r in enumerate(remotes, 1):
        print(f"  {i}. {r}")
    while True:
        try:
            choice = int(input("\nSelect remote (number): ")) - 1
            if 0 <= choice < len(remotes):
                remote = remotes[choice]
                break
        except ValueError:
            pass
        print("Invalid choice, try again.")

    local = input("\nLocal folder path: ").strip()
    if not local:
        print("No path entered.")
        sys.exit(1)

    remote_path = input(f"Remote folder on {remote} (e.g. data, photos/2024): ").strip().strip("/")
    remote_full = f"{remote}:{remote_path}" if remote_path else f"{remote}:"

    batch = prompt_batch()
    log_file = new_log_path()

    print(f"\nSyncing: {local} → {remote_full}")
    print(f"Batch size: {batch}")
    print(f"Log file:   {log_file}")
    print("-" * 50)

    args = copy_args(local, remote_full, batch, log_file)
    run_number = 0
    while True:
        run_number += 1
        print(f"\n── Run {run_number} ──────────────────────────────────")
        start = time.time()
        rc = run(rclone_cmd(*args))
        elapsed = int(time.time() - start)
        mins, secs = divmod(elapsed, 60)
        print(f"\nRun {run_number} finished in {mins}m {secs}s (exit code {rc})")

        if rc == 0:                     # finished — nothing left
            print("\n✓ All done — nothing left to transfer.")
            break
        if rc == 9:                     # --max-transfer hit; more to do
            print("Pausing 3s before next batch…")
            time.sleep(3)
            continue
        print(f"\nWarning: rclone exited with code {rc}. See {log_file}")
        if input("Continue anyway? (y/n): ").strip().lower() != "y":
            break

    print(f"\nLog saved to: {log_file}")
    print("Done.")


if __name__ == "__main__":
    main()
