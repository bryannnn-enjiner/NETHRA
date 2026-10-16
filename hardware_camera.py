# hardware/camera.py
import subprocess
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from PIL import Image
import numpy as np
import cv2


class CameraManager:
    """Manage camera capture dan live preview lewat CLI rpicam-apps
    (rpicam-vid / rpicam-still via subprocess).

    Dipakai alih-alih API Python picamera2 karena binding picamera2/libcamera
    yang terpasang di sistem ini ABI-incompatible (ImportError: undefined
    symbol) walau kamera & CLI tool rpicam-* nya sendiri berfungsi normal.
    Kalau suatu saat Raspberry Pi merilis paket picamera2 yang sudah
    diperbaiki, class ini bisa diganti balik ke API Python tanpa mengubah
    pemanggil (public method signature-nya sama).
    """

    PREVIEW_SIZE = (640, 480)
    # Full sensor FOV, 2x2-binned mode (imx219): forcing this via --mode
    # stops rpicam-vid from silently picking a center-cropped sensor mode
    # just because the requested output size is small.
    SENSOR_MODE = "1640:1232:10:P"
    # Lowered from 20: a lower cap on frame rate raises the max exposure
    # time allowed per frame, gathering more light in the dark exam room -
    # still smooth enough to align by, unlike a preview too dark to see at all.
    PREVIEW_FRAMERATE = 10

    # This is a NoIR sensor (no IR-cut filter), but libcamera identifies it
    # to the OS only as "imx219" and defaults to the standard imx219.json
    # tuning profile, whose colour correction matrix assumes an IR-cut
    # filter is present - that mismatch is what caused the heavy
    # magenta/purple cast in every capture. Forcing the NoIR-specific
    # tuning file fixes it (verified: white balance sample went from
    # BGR≈[84,75,115] to [89,99,108] on the same scene).
    TUNING_FILE = "/usr/local/share/libcamera/ipa/rpi/pisp/imx219_noir.json"

    # The Volk 20D condensing lens forms an inverted, reversed real image of
    # the retina (standard indirect-ophthalmoscopy optics) - rotate 180 to
    # present it right-side up, applied at the ISP level so both the live
    # preview and stills come out already corrected.
    ROTATION = "180"

    # The exam room is normally dark (IR-only illumination for alignment,
    # per the fundus camera literature), leaving an IR-lit scene looking
    # almost black by default. --ev (exposure compensation) turned out to
    # have NO measurable effect here - tested --ev 2/5/8, brightness stayed
    # ~87 every time, meaning auto-exposure was already pinned at some
    # internal gain ceiling --ev can't push past. Forcing --gain directly
    # bypasses that. gain=8 still wasn't enough in the actual dark-room
    # test (screen still looked black); pushed higher after confirming
    # gain=32 clearly reveals detail that gain=8-16 didn't. This is a
    # starting value, not a hard limit - keep raising it if the real
    # dark-room preview is still too dark, at the cost of more noise/grain.
    PREVIEW_GAIN = "16.0"

    # Fixed exposure for the flash-lit still capture. Auto-exposure carries
    # over whatever settings the (dim/ambient) preview converged to, so the
    # sudden bright flash badly overexposed every shot. Empirically tested
    # against a real flash pulse: shutter matched to the flash duration with
    # a modest gain gave sharp, readable detail with minimal clipping -
    # tune further once tested against a real eye rather than a flat test
    # target (see capture_image() note on the remaining glare artifact).
    CAPTURE_SHUTTER_US = "100000"
    CAPTURE_GAIN = "2.0"

    def __init__(self, camera_index=0, resolution=(3280, 2464), format='jpg'):
        self.camera_index = camera_index
        self.resolution = resolution
        self.format = format
        self.capture_dir = Path(__file__).resolve().parent.parent / "captures"
        self.capture_dir.mkdir(exist_ok=True)

        self.available = False
        self.error = None

        self._proc = None
        self._reader_thread = None
        self._stop_event = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._capture_lock = threading.Lock()

        self._init_camera()

    def _init_camera(self):
        try:
            result = subprocess.run(
                ["rpicam-hello", "--list-cameras"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0 or f"{self.camera_index} :" not in result.stdout:
                self.error = "No camera detected"
                return
        except Exception as e:
            self.error = str(e)
            return

        self.available = True
        self._start_preview_stream()

    # ------------------------------------------------------------------
    # Live preview: rpicam-vid streaming MJPEG to stdout, decoded frame by
    # frame in a background thread so get_preview_frame() never blocks.
    # ------------------------------------------------------------------

    def _start_preview_stream(self):
        width, height = self.PREVIEW_SIZE
        cmd = [
            "rpicam-vid",
            "--camera", str(self.camera_index),
            "--mode", self.SENSOR_MODE,
            "--tuning-file", self.TUNING_FILE,
            "--rotation", self.ROTATION,
            "--gain", self.PREVIEW_GAIN,
            "--codec", "mjpeg",
            "-o", "-",
            "--width", str(width),
            "--height", str(height),
            "--framerate", str(self.PREVIEW_FRAMERATE),
            "--timeout", "0",
            "--nopreview",
            "--flush",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
            )
        except Exception as e:
            self.error = str(e)
            return

        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._read_frames, daemon=True)
        self._reader_thread.start()

    def _stop_preview_stream(self):
        self._stop_event.set()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None

    def _read_frames(self):
        """Decode MJPEG frames as they arrive.

        Only the newest complete frame in the buffer is ever decoded: if
        decoding falls even slightly behind the incoming stream, older
        undisplayed frames are dropped (cheap byte-slicing, no JPEG decode)
        instead of being queued up. Without this, preview latency creeps up
        over time and shows up as a laggy, "jumping" image.
        """
        soi, eoi = b"\xff\xd8", b"\xff\xd9"
        buf = b""
        stdout = self._proc.stdout
        while not self._stop_event.is_set():
            chunk = stdout.read(65536)
            if not chunk:
                break
            buf += chunk

            newest_frame = None
            while True:
                start = buf.find(soi)
                if start == -1:
                    buf = b""
                    break
                end = buf.find(eoi, start + 2)
                if end == -1:
                    buf = buf[start:]
                    break
                newest_frame = buf[start:end + 2]
                buf = buf[end + 2:]

            if newest_frame:
                try:
                    img = Image.open(BytesIO(newest_frame)).convert("RGB")
                    with self._frame_lock:
                        self._latest_frame = np.array(img)
                except Exception:
                    pass

    def get_preview_frame(self):
        """Return the latest preview frame as an (H, W, 3) RGB numpy array, or None."""
        if not self.available:
            return None
        with self._frame_lock:
            return self._latest_frame

    def get_focus_score(self):
        """Laplacian-variance sharpness of the latest preview frame - higher
        is sharper, no fixed "good" threshold (depends on the scene), but it
        rises and falls monotonically with focus quality. This module ships
        factory-focused for ~1m+/infinity; the fundus rig needs close-range
        focus, so this is meant as a live readout to maximize while manually
        turning the lens's focus ring, instead of guessing and re-capturing."""
        frame = self.get_preview_frame()
        if frame is None:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    # ------------------------------------------------------------------
    # Still capture: briefly pause the preview stream (camera is exclusive
    # to one process at a time), shoot a full-res still, resume preview.
    # ------------------------------------------------------------------

    def capture_image(self, flash_led_callback=None):
        """
        Capture a full-resolution still image.

        Known remaining artifact: flash-lit captures show a fixed bright
        twin-blob glare near frame centre that persists across a wide range
        of CAPTURE_SHUTTER_US/CAPTURE_GAIN values - this points to a direct
        specular reflection of the ring flash (not general overexposure,
        which exposure tuning could fix). Tested against flat glossy paper,
        which is a poor stand-in for a real curved eye; if this also shows
        up against a real eye it's the classic fundus-camera corneal
        reflection problem, fixed physically (diffusing/angling the ring,
        increasing working distance) rather than in software.

        Returns:
            (success: bool, filename: str, error_msg: str)
        """
        if not self.available:
            return (False, None, self.error or "Camera not connected")

        with self._capture_lock:
            try:
                self._stop_preview_stream()

                timestamp = int(time.time())
                filename = str(self.capture_dir / f"capture_{timestamp}.{self.format}")
                width, height = self.resolution

                cmd = [
                    "rpicam-still",
                    "--camera", str(self.camera_index),
                    "--tuning-file", self.TUNING_FILE,
                    "--rotation", self.ROTATION,
                    "--shutter", self.CAPTURE_SHUTTER_US,
                    "--gain", self.CAPTURE_GAIN,
                    "-o", filename,
                    "--width", str(width),
                    "--height", str(height),
                    "--immediate",
                    "--nopreview",
                ]

                # Flash is switched on right around the actual shutter call (not
                # earlier) so it's genuinely lit while the sensor captures -
                # turning it on before _stop_preview_stream() meant it had
                # already gone dark by the time rpicam-still really ran.
                try:
                    if flash_led_callback:
                        flash_led_callback('on')
                    result = subprocess.run(cmd, capture_output=True, timeout=10)
                finally:
                    if flash_led_callback:
                        flash_led_callback('off')

                success = result.returncode == 0
                error = None if success else (
                    result.stderr.decode(errors='ignore').strip() or "Camera capture failed"
                )
                return (success, filename if success else None, error)

            except subprocess.TimeoutExpired:
                return (False, None, "Camera timeout")
            except Exception as e:
                return (False, None, str(e))
            finally:
                self._start_preview_stream()

    def organize_capture(self, filepath, class_name):
        """Move a freshly classified capture into captures/{class_name}/ with a
        clean, sortable filename. Returns the new path (or the original path
        if the move fails)."""
        try:
            src = Path(filepath)
            class_dir = self.capture_dir / class_name
            class_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = class_dir / f"{class_name}_{timestamp}{src.suffix}"
            counter = 1
            while dest.exists():
                dest = class_dir / f"{class_name}_{timestamp}_{counter}{src.suffix}"
                counter += 1

            src.rename(dest)
            return str(dest)
        except Exception:
            return filepath

    def get_image_class(self, filepath):
        """Return the classification label for an image, inferred from its
        parent subfolder (captures/NPDR/, captures/Normal/, captures/PDR/),
        or None if it's an unclassified image directly in captures/."""
        parent = Path(filepath).parent
        if parent == self.capture_dir:
            return None
        return parent.name

    def get_capture_list(self):
        """Get list of captured images, across classified subfolders and any
        unclassified images left directly in captures/."""
        try:
            files = set(self.capture_dir.glob(f"*.{self.format}"))
            for class_dir in self.capture_dir.iterdir():
                if class_dir.is_dir():
                    files.update(class_dir.glob(f"*.{self.format}"))

            ordered = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
            return [str(f) for f in ordered]
        except Exception:
            return []

    def get_image_thumbnail(self, filepath, size=(480, 320)):
        """Get image thumbnail for display"""
        try:
            img = Image.open(filepath)
            img.thumbnail(size, Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            print(f"Error loading image: {e}")
            return None

    def get_image_info(self, filepath):
        """Get image information"""
        try:
            path = Path(filepath)
            img = Image.open(filepath)
            size_mb = path.stat().st_size / (1024 * 1024)

            return {
                'filename': path.name,
                'size_mb': f"{size_mb:.2f}",
                'resolution': f"{img.width}x{img.height}",
                'path': filepath
            }
        except Exception:
            return None

    def delete_image(self, filepath):
        """Delete image file"""
        try:
            Path(filepath).unlink()
            return True
        except Exception:
            return False

    def close(self):
        """Release the camera"""
        self._stop_preview_stream()
