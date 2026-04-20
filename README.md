# simple-rclone

A minimal tkinter GUI and CLI tool for syncing files with rclone (Proton Drive or any rclone remote).

## Files

| File | Description |
|------|-------------|
| `pdrive.py` | Tkinter GUI — upload/download with folder pickers, saved connections, auto-batch |
| `sync_batch.py` | CLI batch sync — interactive prompts, loops until all files transferred |

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

Sync logs stream to the terminal window.

### CLI batch sync

```bash
python sync_batch.py
```

Prompts for remote, local folder, remote path, and batch size — then loops `rclone copy` until everything is transferred.

## How auto-batch works

rclone's `--max-transfer` flag stops a run after transferring the specified amount. Auto-batch re-runs automatically until nothing is left to transfer, working around Proton Drive API rate limits.
