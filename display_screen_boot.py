# display/screen_boot.py
import time
from pathlib import Path
import pygame
from config.wifi_network import network_manager

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


class BootScreen:
    """Branded boot sequence.

    1. Show the logo (drop a PNG at assets/logo.png to replace the text
       placeholder - it's picked up automatically, no code changes needed).
    2. Show a "Connecting to WiFi..." status while the already-configured
       network comes up, up to `timeout` seconds.
    3. Hand off to the main screen in online or offline mode.
    """

    LOGO_DURATION = 1.6
    WIFI_POLL_INTERVAL = 0.3

    def __init__(self, ui_helper, width, height, colors, timeout=5):
        self.ui = ui_helper
        self.width = width
        self.height = height
        self.colors = colors
        self.wifi_timeout = timeout

        self._logo_surface = self._load_logo()

    def _load_logo(self):
        if not LOGO_PATH.exists():
            return None
        try:
            img = pygame.image.load(str(LOGO_PATH)).convert_alpha()
            max_w, max_h = int(self.width * 0.7), int(self.height * 0.5)
            scale = min(max_w / img.get_width(), max_h / img.get_height(), 1.0)
            size = (max(1, int(img.get_width() * scale)), max(1, int(img.get_height() * scale)))
            return pygame.transform.smoothscale(img, size)
        except Exception:
            return None

    def _draw_logo(self, screen, y_offset=0):
        """Draw the logo image if available, otherwise a text wordmark. Returns bottom y."""
        if self._logo_surface:
            x = (self.width - self._logo_surface.get_width()) // 2
            y = (self.height - self._logo_surface.get_height()) // 2 + y_offset
            screen.blit(self._logo_surface, (x, y))
            return y + self._logo_surface.get_height()
        else:
            y = self.height // 2 - 20 + y_offset
            surface = self.ui.draw_text_centered(screen, "EyeXaminer", y,
                                                   self.ui.font_title, self.colors['text_primary'])
            return y + surface.get_height()

    def _render_logo_only(self, screen):
        screen.fill(self.colors['bg_primary'])
        self._draw_logo(screen)
        pygame.display.update()

    def _render_connecting(self, screen, dots):
        screen.fill(self.colors['bg_primary'])
        bottom = self._draw_logo(screen, y_offset=-30)

        msg = "Connecting to WiFi" + "." * dots
        self.ui.draw_text_centered(screen, msg, bottom + 20,
                                    self.ui.font_small, self.colors['text_muted'])
        pygame.display.update()

    def show(self, screen):
        """Run the boot sequence. Returns is_connected: bool"""
        self._render_logo_only(screen)
        time.sleep(self.LOGO_DURATION)

        start_time = time.time()
        is_connected = False
        tick = 0
        while time.time() - start_time < self.wifi_timeout:
            is_connected = network_manager.check_now(timeout=0.8)
            if is_connected:
                break
            self._render_connecting(screen, tick % 4)
            tick += 1
            time.sleep(self.WIFI_POLL_INTERVAL)

        return is_connected
