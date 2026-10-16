# display/screen_main.py
import time
import pygame
from config.wifi_network import network_manager
from hardware.hardware_battery import battery_monitor


class MainScreen:
    """Main screen: live retina camera preview + Capture / Gallery footer"""

    MARGIN = 14

    def __init__(self, ui_helper, width, height, colors):
        self.ui = ui_helper
        self.width = width
        self.height = height
        self.colors = colors

        self.last_message = None
        self.message_start_time = None
        self.message_duration = 2.0  # detik

        self.is_classifying = False
        self.classification_result = None
        self.result_start_time = None
        self.result_duration = 6.0  # detik - diagnostic text needs more time to read than a toast

        self.flash_toggle_message = None
        self.flash_toggle_time = None

        self.flash_hold_progress = 0.0

    def show_flash_toggled(self, enabled):
        self.flash_toggle_message = "Flash On" if enabled else "Flash Off"
        self.flash_toggle_time = time.time()

    def is_flash_toggle_message_visible(self):
        if self.flash_toggle_message is None:
            return False
        if time.time() - self.flash_toggle_time >= self.message_duration:
            self.flash_toggle_message = None
            return False
        return True

    def set_flash_hold_progress(self, progress):
        """0.0-1.0 while the Gallery button is held past a tap on the main
        screen, driving the flash on/off toggle progress indicator."""
        self.flash_hold_progress = progress

    def show_capture_success(self, filename):
        """Store message untuk ditampilkan"""
        self.last_message = "Image Saved"
        self.message_start_time = time.time()

    def show_capture_error(self, error):
        self.last_message = "Capture Failed"
        self.message_start_time = time.time()

    def show_classifying(self):
        """Capture succeeded and classification has been kicked off in the
        background; show a spinner over the preview until the result lands."""
        self.is_classifying = True
        self.classification_result = None
        self.last_message = None

    def show_classification_result(self, class_name, confidence):
        self.is_classifying = False
        self.classification_result = {'class_name': class_name, 'confidence': confidence}
        self.result_start_time = time.time()

    def is_message_visible(self):
        """Check if message masih harus ditampilkan"""
        if self.last_message is None:
            return False

        elapsed = time.time() - self.message_start_time
        if elapsed >= self.message_duration:
            self.last_message = None
            return False

        return True

    def is_result_visible(self):
        if self.classification_result is None:
            return False

        elapsed = time.time() - self.result_start_time
        if elapsed >= self.result_duration:
            self.classification_result = None
            return False

        return True

    def render(self, screen, camera_preview_surface=None, camera_state='unavailable',
               camera_status_text=None, focus_score=None, flash_enabled=True):
        """
        Render main screen

        Args:
            screen: pygame screen
            camera_preview_surface: pygame.Surface with the latest frame, or None
            camera_state: 'live' | 'loading' | 'unavailable'
            camera_status_text: optional override message for loading/unavailable states
            focus_score: live sharpness readout (Laplacian variance) to help
                manually tune the NoIR camera's focus ring, or None
            flash_enabled: whether the capture flash will fire (hold Gallery
                button to toggle) - shows a badge when disabled
        """
        self.ui.draw_background(screen)

        is_connected = network_manager.is_wifi_connected()
        mode = "online" if is_connected else "offline"
        bar_h = self.ui.draw_status_bar(screen, mode, title="EyeXaminer",
                                         battery_percentage=battery_monitor.get_percentage())

        preview_x = self.MARGIN
        preview_y = bar_h + 8
        preview_width = self.width - self.MARGIN * 2
        preview_height = self.height - self.ui.FOOTER_HEIGHT - preview_y - 8

        self.ui.draw_camera_frame(
            screen, preview_x, preview_y, preview_width, preview_height,
            preview_surface=camera_preview_surface,
            state=camera_state,
            status_text=camera_status_text,
        )

        self.ui.draw_footer(screen, 'shutter', 'Capture', 'gallery', 'Gallery')

        if focus_score is not None:
            self.ui.draw_focus_score(screen, focus_score, preview_x, preview_y, preview_width)

        if not flash_enabled:
            self.ui.draw_flash_off_badge(screen, preview_x, preview_y)

        if self.flash_hold_progress > 0:
            hold_y = self.height - self.ui.FOOTER_HEIGHT - 20
            self.ui.draw_hold_progress(screen, self.flash_hold_progress, hold_y)
        elif self.is_classifying:
            self.ui.draw_spinner_overlay(screen, preview_x, preview_y, preview_width, preview_height,
                                          message="Analyzing image...")
        elif self.is_result_visible():
            r = self.classification_result
            self.ui.draw_classification_result(screen, r['class_name'], r['confidence'])
        elif self.is_flash_toggle_message_visible():
            self.ui.draw_toast(screen, self.flash_toggle_message, color=self.colors['accent_blue'])
        elif self.is_message_visible():
            is_error = self.last_message == "Capture Failed"
            color = self.colors['danger_red'] if is_error else self.colors['success_green']
            self.ui.draw_toast(screen, self.last_message, color=color)

        pygame.display.update()
