# bebird_desktop

Based on the work at https://myth.cx/p/bebird-protocol/, further enhanced as a desktop alternative to the official BeBird mobile app.

## How It Works

The camera broadcasts MJPEG over UDP as fragmented packets. Each packet has a 4-byte header:

| Byte | Field | Description |
|------|-------|-------------|
| B0 | `frame_id` | Wraps 0–255, increments per frame |
| B1 | `is_last` | `0x00` = regular fragment, `0x01` = final fragment |
| B2 | `frag_idx` | 1-based fragment index within a frame |
| B3 | `frag_type` | `0x08` for data, `~0x6e` for final fragment |

Fragments are reassembled in order and each complete JPEG is validated before display.

## Requirements

- Python 3.10+
- opencv-python
- Pillow
- NumPy
- PySide6

Install dependencies:

```bash
pip install -r requirements.txt
```

## Setup

Connect to the bebird camera's Wi-Fi network. The device is expected at `192.168.5.1:58080` by default.

## Usage

```bash
python bebird_desktop.py
```

The window scales the video feed automatically as you resize it. Controls at the bottom of the window:

- **Connect / Disconnect** — start or stop the stream
- **Start / Stop Saving** — saves all frames to a timestamped subfolder while active
- **Live stats** — frames received and dropped shown in the status bar

## Saved Frames

When saving is enabled, a subfolder named with the current timestamp is created (e.g. `20260302_143512/`) and frames are written sequentially as `frame_00000.png`, `frame_00001.png`, etc.

## Configuration

Edit the constants at the top of `bebird_desktop.py` to change the device address or port:

```python
DEVICE_IP   = "192.168.5.1"
DEVICE_PORT = 58080
```

## Building a Standalone App

Use `python -m PyInstaller` to ensure PyInstaller uses the same Python environment where the dependencies are installed.

Install PyInstaller first:

```bash
pip install pyinstaller
```

### macOS

```bash
rm -rf build dist
python -m PyInstaller --windowed \
                      --name "bebird Viewer" \
                      --collect-all PySide6 \
                      --collect-all cv2 \
                      bebird_desktop.py
```

Output: `dist/bebird Viewer.app` — double-clickable app bundle.

Optionally package as a `.dmg`:

```bash
hdiutil create -volname "bebird Viewer" \
               -srcfolder "dist/bebird Viewer.app" \
               -ov -format UDZO \
               "bebird Viewer.dmg"
```

### Windows

```bash
rd /s /q build dist
python -m PyInstaller --windowed --onefile ^
                      --name "bebird Viewer" ^
                      --collect-all PySide6 ^
                      --collect-all cv2 ^
                      bebird_desktop.py
```

Output: `dist/bebird Viewer.exe` — single portable executable.

> **Note:** Build on the target OS — PyInstaller does not cross-compile.

## License

This project is licensed under the GNU General Public License v3.0.

You are free to:

    Use, study, and modify the code
    Distribute copies or modified versions under the same license

However, any software derived from this project must also be open source under the GPLv3 terms.

See the full license here: https://www.gnu.org/licenses/gpl-3.0.en.html
