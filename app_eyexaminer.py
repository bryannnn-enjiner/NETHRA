# app_eyexaminer.py
import os
import sys
import time
import pygame
import numpy as np
from config.config_settings import settings
from hardware.hardware_gpio import GPIOController
from hardware.hardware_camera import CameraManager
from hardware.hardware_classifier import ClassifierManager
from config.wifi_network import network_manager
from display.display_ui import UIHelper
from display.display_screen_boot import BootScreen
from display.display_screen_main import MainScreen
from display.display_screen_gallery import GalleryScreen
from utils.utils_logger import logger

class EyeExaminerApp:
    """Main application"""
    
    def __init__(self):
        # Set SDL environment
        os.environ["SDL_FBDEV"] = settings.fbdev
        
        # Initialize pygame
        pygame.init()
        self.screen = pygame.display.set_mode(
            (settings.display_width, settings.display_height),
            pygame.FULLSCREEN | pygame.NOFRAME
        )
        pygame.mouse.set_visible(False)
        
        # Store settings
        self.colors = {
            'bg_primary': settings.color_bg_primary,
            'bg_card': settings.color_bg_card,
            'text_primary': settings.color_text_primary,
            'text_muted': settings.color_text_muted,
            'accent_blue': settings.color_accent_blue,
            'success_green': settings.color_success_green,
            'warning_yellow': settings.color_warning_yellow,
            'danger_red': settings.color_danger_red,
            'class_orange': settings.color_class_orange,
        }

        # Initialize components
        self.ui = UIHelper(settings.display_width, settings.display_height, self.colors)
        self.gpio = GPIOController(
            settings.btn_capture_pin,
            settings.btn_menu_pin,
            settings.ir_led_pins,
            {
                'gpio_pin': settings.rgb_flash_gpio_pin,
                'led_count': settings.rgb_flash_led_count,
                'brightness': settings.rgb_flash_brightness,
                'duration': settings.rgb_flash_duration,
                'dma_channel': settings.rgb_flash_dma_channel,
            }
        )
        if not self.gpio.flash_available:
            logger.warning(f"RGB flash not available: {self.gpio.flash_error}")
        self.camera = CameraManager(
            settings.camera_index,
            settings.camera_resolution,
            settings.camera_format
        )
        if not self.camera.available:
            logger.warning(f"Camera not available: {self.camera.error}")

        self.classifier = ClassifierManager()
        if not self.classifier.available:
            logger.warning(f"Classifier not available: {self.classifier.error}")
        self._pending_classify_path = None

        # Initialize screens
        self.boot_screen = BootScreen(self.ui, settings.display_width, settings.display_height, self.colors, settings.boot_timeout)
        self.main_screen = MainScreen(self.ui, settings.display_width, settings.display_height, self.colors)
        self.gallery_screen = GalleryScreen(self.ui, settings.display_width, settings.display_height, self.colors, self.camera)
        
        # State
        self.current_screen = "boot"
        self.is_connected = False
        self.running = True
        self.last_button_time = 0
        self.button_debounce = 0.5  # seconds

        # Gallery gestures: tap left/right = prev/next, hold left = home,
        # hold right = open delete confirmation dialog
        self._left_hold_start = None
        self._left_hold_fired = False
        self._right_hold_start = None
        self._right_hold_fired = False
        self.gallery_hold_threshold = 1.5  # seconds

        # Main screen: tap Gallery button = go to Gallery (existing), hold
        # past threshold = toggle the capture flash on/off instead (some
        # subjects/lighting conditions don't want the bright ring flash).
        self.flash_enabled = True
        self._menu_hold_start = None
        self._menu_hold_fired = False
        self.flash_toggle_hold_threshold = 1.2  # seconds

    def flash_callback(self, state):
        """Callback untuk flash LED control.

        IR is momentarily switched off for the white flash + actual shutter
        (then back on right after), matching the NoIR fundus camera approach
        in PMC5370517 - the NoIR sensor is IR-sensitive, so leaving IR on
        during the visible-light exposure can skew the captured colors.
        IR stays on the rest of the time for alignment.
        """
        if state == 'on':
            self.gpio.ir_led_off()
            self.gpio.flash_on()
        else:
            self.gpio.flash_off()
            self.gpio.ir_led_on()
    
    def handle_events(self):
        """Handle pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
    
    def update_boot_screen(self):
        """Update and handle boot screen"""
        self.is_connected = self.boot_screen.show(self.screen)
        self.current_screen = "main"
    
    def get_preview_surface(self):
        """Grab the latest camera frame and convert it to a pygame Surface.

        Returns (surface_or_None, state) where state is one of
        'live' | 'loading' | 'unavailable'.
        """
        if not self.camera.available:
            return None, 'unavailable'

        frame = self.camera.get_preview_frame()
        if frame is None:
            return None, 'loading'

        # The live preview scene is either ambient-lit (bench testing) or
        # IR-only-lit (real dark-room exam use - IR LEDs stay on for
        # alignment). Under IR alone a colour sensor renders the scene as a
        # meaningless purple/magenta wash (IR triggers the Bayer red/blue
        # photosites more than green; there's no real colour to white-balance
        # against). The actual retinal structure is in the luminance, not
        # the colour, so discarding colour and showing grayscale makes it
        # legible instead of a purple blur either way.
        height, width = frame.shape[:2]
        gray = np.dot(frame[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)
        gray_rgb = np.stack([gray, gray, gray], axis=-1)
        surface = pygame.image.frombuffer(gray_rgb.tobytes(), (width, height), "RGB")
        return surface, 'live'

    def update_main_screen(self):
        """Update and handle main screen.

        Gallery button: tap = go to Gallery, hold past
        flash_toggle_hold_threshold = toggle the capture flash on/off
        instead (release does not navigate to Gallery in that case).
        """
        # Check buttons dengan debounce
        current_time = time.time()

        if self.gpio.is_menu_pressed():
            if self._menu_hold_start is None:
                self._menu_hold_start = current_time
                self._menu_hold_fired = False
            hold_duration = current_time - self._menu_hold_start
            self.main_screen.set_flash_hold_progress(
                min(hold_duration / self.flash_toggle_hold_threshold, 1.0))

            if hold_duration >= self.flash_toggle_hold_threshold and not self._menu_hold_fired:
                self._menu_hold_fired = True
                self.main_screen.set_flash_hold_progress(0.0)
                self.flash_enabled = not self.flash_enabled
                self.main_screen.show_flash_toggled(self.flash_enabled)
                self.last_button_time = current_time

        elif self._menu_hold_start is not None:
            was_fired = self._menu_hold_fired
            self._menu_hold_start = None
            self.main_screen.set_flash_hold_progress(0.0)
            if not was_fired and current_time - self.last_button_time > self.button_debounce:
                # Was a tap, not a hold - go to gallery
                self.current_screen = "gallery"
                self.last_button_time = current_time
                self.gallery_screen.reload_images()

        elif self.gpio.is_capture_pressed():
            # Capture image
            if current_time - self.last_button_time > self.button_debounce:
                capture_flash_callback = self.flash_callback if self.flash_enabled else None
                success, filename, error = self.camera.capture_image(capture_flash_callback)
                if success:
                    if self.classifier.available:
                        self.main_screen.show_classifying()
                        self._pending_classify_path = filename
                        self.classifier.classify_async(filename)
                    else:
                        self.main_screen.show_capture_success(filename)
                else:
                    logger.warning(f"Capture failed: {error}")
                    self.main_screen.show_capture_error(error)
                self.last_button_time = current_time

        if self._pending_classify_path and not self.classifier.is_busy():
            result = self.classifier.get_result()
            path = self._pending_classify_path
            self._pending_classify_path = None
            if result and not result.get('error'):
                class_name = result['class_name']
                self.camera.organize_capture(path, class_name)
                self.main_screen.show_classification_result(class_name, result['confidence'])
            else:
                logger.warning(f"Classification failed: {result.get('error') if result else 'unknown error'}")
                self.main_screen.show_capture_error("Classification failed")

        preview_surface, camera_state = self.get_preview_surface()
        focus_score = self.camera.get_focus_score() if camera_state == 'live' else None
        self.main_screen.render(
            self.screen,
            camera_preview_surface=preview_surface,
            camera_state=camera_state,
            focus_score=focus_score,
            flash_enabled=self.flash_enabled,
        )

        time.sleep(settings.preview_update_interval)
    
    def update_gallery_screen(self):
        """Update and handle gallery screen.

        Normal browsing: tap left = prev, tap right = next.
        Hold left past threshold = go home. Hold right past threshold =
        open the delete confirmation dialog (separate from actually
        deleting, so it can't happen by accident).

        While the confirmation dialog is open: tap left toggles the
        Yes/No selection, tap right confirms it.
        """
        current_time = time.time()

        if self.gallery_screen.confirm_delete_open:
            if self.gpio.is_capture_pressed():
                if current_time - self.last_button_time > self.button_debounce:
                    self.gallery_screen.toggle_delete_selection()
                    self.last_button_time = current_time
            elif self.gpio.is_menu_pressed():
                if current_time - self.last_button_time > self.button_debounce:
                    if self.gallery_screen.delete_selection == 'yes':
                        current_path = self.gallery_screen.get_current_image()
                        if current_path:
                            self.camera.delete_image(current_path)
                            self.gallery_screen.reload_images()
                            self.gallery_screen.show_deleted_toast()
                    self.gallery_screen.close_delete_confirm()
                    self.last_button_time = current_time

        else:
            # Left button: tap = prev, hold = go home
            if self.gpio.is_capture_pressed():
                if self._left_hold_start is None:
                    self._left_hold_start = current_time
                    self._left_hold_fired = False
                hold_duration = current_time - self._left_hold_start
                self.gallery_screen.set_home_hold_progress(
                    min(hold_duration / self.gallery_hold_threshold, 1.0))

                if hold_duration >= self.gallery_hold_threshold and not self._left_hold_fired:
                    self._left_hold_fired = True
                    self.gallery_screen.set_home_hold_progress(0.0)
                    self.current_screen = "main"
                    self.last_button_time = current_time
            elif self._left_hold_start is not None:
                was_fired = self._left_hold_fired
                self._left_hold_start = None
                self.gallery_screen.set_home_hold_progress(0.0)
                if not was_fired and current_time - self.last_button_time > self.button_debounce:
                    self.gallery_screen.prev_image()
                    self.last_button_time = current_time

            # Right button: tap = next, hold = open delete confirmation
            if self.gpio.is_menu_pressed():
                if self._right_hold_start is None:
                    self._right_hold_start = current_time
                    self._right_hold_fired = False
                hold_duration = current_time - self._right_hold_start
                self.gallery_screen.set_delete_hold_progress(
                    min(hold_duration / self.gallery_hold_threshold, 1.0))

                if hold_duration >= self.gallery_hold_threshold and not self._right_hold_fired:
                    self._right_hold_fired = True
                    self.gallery_screen.set_delete_hold_progress(0.0)
                    self.gallery_screen.open_delete_confirm()
                    self.last_button_time = current_time
            elif self._right_hold_start is not None:
                was_fired = self._right_hold_fired
                self._right_hold_start = None
                self.gallery_screen.set_delete_hold_progress(0.0)
                if not was_fired and current_time - self.last_button_time > self.button_debounce:
                    self.gallery_screen.next_image()
                    self.last_button_time = current_time

        # Render gallery screen
        self.gallery_screen.render(self.screen)

        time.sleep(0.05)
    
    def run(self):
        """Main application loop"""
        try:
            while self.running:
                self.handle_events()
                
                if self.current_screen == "boot":
                    self.update_boot_screen()
                elif self.current_screen == "main":
                    self.update_main_screen()
                elif self.current_screen == "gallery":
                    self.update_gallery_screen()
        
        except KeyboardInterrupt:
            print("\nProgram stopped by user")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        self.gpio.cleanup()
        self.camera.close()
        pygame.quit()
        sys.exit()


def main():
    """Entry point"""
    app = EyeExaminerApp()
    app.run()


if __name__ == "__main__":
    main()
