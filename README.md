# simple-rclone

A minimal tkinter GUI and CLI tool for syncing files with rclone (Proton Drive or any rclone remote).

## Files

| File | Description |
|------|-------------|
| `pdrive.py` | Tkinter GUI — folder pickers, saved connections, live log + progress bar, cancel button |
| `sync_batch.py` | CLI batch sync — interactive prompts, loops until all files transferred |
| `rclone_common.py` | Shared flags, log paths, and helpers used by both front ends |

## Requirements

- Python 3.8+
- `rclone` installed and configured (`rclone config`)
- `tkinter` (included with most Python installs; on Debian/Ubuntu: `sudo apt install python3-tk`)

No pip dependencies.

## Usage

### GUI

```bash
python pdrive.py
```

- Pick a remote from the dropdown
- Choose upload (local → remote) or download (remote → local)
- Browse local and remote folders
- Set batch size (e.g. `2G`) and toggle auto-batch
- Save connections for quick reuse
- Live log pane, progress bar, and cancel button while a sync runs
- `Enter` starts a sync, `Esc` closes a dialog

Full rclone output is also written to `~/.cache/simple-rclone/rclone-<timestamp>.log`.

### CLI batch sync

```bash
python sync_batch.py
```

Prompts for remote, local folder, remote path, and batch size — then loops `rclone copy` until everything is transferred.

## Compare — verify a sync

After a run, confirm that every source file landed on the destination:

- **GUI:** click the green `✓` button next to any saved connection, or the
  `Compare` button that appears once a sync finishes successfully.
- **CLI:** answer `y` to the `Run compare to verify…` prompt at the end of
  a run.

Under the hood: `rclone check <src> <dst> --one-way --size-only`. Exit `0`
means every source file is on the destination with matching size; anything
else means re-run the sync. One-way mirrors the `copy` semantics (extras on
the destination are ignored); size-only skips hashing so it's fast and works
on remotes without hash support.

## How auto-batch works

rclone's `--max-transfer` flag stops a run after transferring the specified amount, exiting with code `9`. Auto-batch re-runs automatically until rclone exits with `0` (nothing left to transfer), which works around Proton Drive API rate limits without parsing log text.

## Defaults applied to every run

Set in `rclone_common.py` so both front ends behave identically:

- `--transfers 4 --checkers 8`
- `--ignore-existing` (skip files already on the destination)
- `--fast-list` (fewer API calls on remotes that support it)
- `--retries 3 --low-level-retries 10 --retries-sleep 10s`
- `--drive-pacer-min-sleep 10ms --drive-pacer-burst 200`
- `--log-file <rotating>  --log-level INFO`
