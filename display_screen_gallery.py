# display/screen_gallery.py
import time
import pygame
from config.wifi_network import network_manager
from hardware.hardware_battery import battery_monitor


class GalleryScreen:
    """Gallery screen untuk browse captured retina images"""

    MARGIN = 14
    # Reserved band between the image card and the footer for the hold
    # hint/progress bar - large enough that it never overlaps the card above
    # or the footer icons below.
    HINT_AREA_HEIGHT = 26
    # Fixed (theme-independent) scrim for the caption bar drawn over a photo,
    # so filename text stays legible regardless of the app's light/dark theme.
    CAPTION_SCRIM = (15, 23, 42)
    CAPTION_TEXT = (248, 250, 252)
    CAPTION_TEXT_MUTED = (148, 163, 184)

    def __init__(self, ui_helper, width, height, colors, camera_manager):
        self.ui = ui_helper
        self.width = width
        self.height = height
        self.colors = colors
        self.camera = camera_manager

        self.current_index = 0
        self.images = []
        self.reload_images()

        self.home_hold_progress = 0.0
        self.delete_hold_progress = 0.0
        self.confirm_delete_open = False
        self.delete_selection = 'no'
        self.last_message = None
        self.message_start_time = None
        self.message_duration = 2.0

    def set_home_hold_progress(self, progress):
        """0.0-1.0 while the left button is held, driving the hold-to-go-home
        progress indicator instead of the normal hint."""
        self.home_hold_progress = progress

    def set_delete_hold_progress(self, progress):
        """0.0-1.0 while the right button is held, driving the progress
        indicator toward opening the delete confirmation dialog."""
        self.delete_hold_progress = progress

    def open_delete_confirm(self):
        self.confirm_delete_open = True
        self.delete_selection = 'no'  # safer default - requires a deliberate move to Yes

    def close_delete_confirm(self):
        self.confirm_delete_open = False

    def toggle_delete_selection(self):
        self.delete_selection = 'yes' if self.delete_selection == 'no' else 'no'

    def show_deleted_toast(self):
        self.last_message = "Image Deleted"
        self.message_start_time = time.time()

    def is_message_visible(self):
        if self.last_message is None:
            return False
        if time.time() - self.message_start_time >= self.message_duration:
            self.last_message = None
            return False
        return True

    def reload_images(self):
        """Reload list of captured images"""
        self.images = self.camera.get_capture_list()
        if not self.images:
            self.current_index = 0
        elif self.current_index >= len(self.images):
            self.current_index = len(self.images) - 1

    def next_image(self):
        """Go to next image"""
        if self.images:
            self.current_index = (self.current_index - 1) % len(self.images)

    def prev_image(self):
        """Go to previous image"""
        if self.images:
            self.current_index = (self.current_index + 1) % len(self.images)

    def get_current_image(self):
        """Get current image path"""
        if self.images and 0 <= self.current_index < len(self.images):
            return self.images[self.current_index]
        return None

    def render(self, screen):
        """Render gallery screen"""
        self.ui.draw_background(screen)

        is_connected = network_manager.is_wifi_connected()
        mode = "online" if is_connected else "offline"
        bar_h = self.ui.draw_status_bar(screen, mode, title="Gallery",
                                         battery_percentage=battery_monitor.get_percentage())

        card_x = self.MARGIN
        card_y = bar_h + 8
        card_width = self.width - self.MARGIN * 2
        card_height = self.height - self.ui.FOOTER_HEIGHT - self.HINT_AREA_HEIGHT - card_y

        if not self.images:
            self._render_empty_state(screen, card_x, card_y, card_width, card_height)
        else:
            self.ui.draw_pill(screen, f"{self.current_index + 1} / {len(self.images)}",
                               card_x, card_y - 2, color=self.colors['bg_card'],
                               text_color=self.colors['text_muted'], font=self.ui.font_micro)

            self._render_image_card(screen, card_x, card_y, card_width, card_height)

        self.ui.draw_footer(screen, 'prev', 'Prev', 'next', 'Next')

        hint_y = card_y + card_height + (self.HINT_AREA_HEIGHT - 12) // 2
        if self.home_hold_progress > 0:
            self.ui.draw_hold_progress(screen, self.home_hold_progress, hint_y)
        elif self.delete_hold_progress > 0:
            self.ui.draw_hold_progress(screen, self.delete_hold_progress, hint_y)
        elif self.is_message_visible():
            self.ui.draw_toast(screen, self.last_message, color=self.colors['accent_blue'])
        else:
            self.ui.draw_text_centered(screen, "Hold Kiri = Home  •  Hold Kanan = Delete", hint_y,
                                        self.ui.font_micro, self.colors['text_muted'])

        if self.confirm_delete_open:
            self.ui.draw_delete_confirm_dialog(screen, self.delete_selection)

        pygame.display.update()

    def _render_empty_state(self, screen, x, y, width, height):
        pygame.draw.rect(screen, self.colors['bg_card'], (x, y, width, height), border_radius=14)
        cx, cy = x + width // 2, y + height // 2 - 16
        self.ui._draw_icon_gallery(screen, cx, cy, 34, self.colors['text_muted'])

        self.ui.draw_text_centered(screen, "No images captured yet", cy + 40,
                                    self.ui.font_small, self.colors['text_primary'])
        self.ui.draw_text_centered(screen, "Captured retina images will appear here", cy + 64,
                                    self.ui.font_micro, self.colors['text_muted'])

    def _render_image_card(self, screen, x, y, width, height):
        pygame.draw.rect(screen, self.colors['bg_card'], (x, y, width, height), border_radius=14)

        current_img_path = self.get_current_image()
        img_info = None
        if current_img_path:
            inner = pygame.Rect(x + 2, y + 2, width - 4, height - 4)
            # PIL's thumbnail() already preserves aspect ratio (shrinks to fit
            # within thumb_size, doesn't force it) - just center that result
            # instead of smoothscale-ing it again to the exact card size,
            # which was stretching every photo to fill the card ("gepeng").
            img = self.camera.get_image_thumbnail(current_img_path, (inner.width, inner.height))
            if img:
                img_surface = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
                draw_x = inner.x + (inner.width - img.size[0]) // 2
                draw_y = inner.y + (inner.height - img.size[1]) // 2
                screen.blit(img_surface, (draw_x, draw_y))

            img_info = self.camera.get_image_info(current_img_path)

        border_color = self.colors['accent_blue']
        img_class = self.camera.get_image_class(current_img_path) if current_img_path else None
        if img_class:
            border_color = self.ui.classification_color(img_class)

        pygame.draw.rect(screen, border_color, (x, y, width, height), 2, border_radius=14)

        if img_class:
            font = self.ui.font_small
            badge_color = self.ui.classification_color(img_class)
            pad_x, pad_y = 10, 4
            text_w, text_h = font.size(img_class)
            badge_w = text_w + pad_x * 2
            badge_x = x + width - badge_w - 10
            badge_y = y + 10
            self.ui.draw_pill(screen, img_class, badge_x, badge_y,
                               color=self.CAPTION_SCRIM, text_color=badge_color, font=font)

        if img_info:
            caption_h = 34
            caption_y = y + height - caption_h
            caption_surface = pygame.Surface((width, caption_h), pygame.SRCALPHA)
            pygame.draw.rect(caption_surface, (*self.CAPTION_SCRIM, 190),
                              (0, 0, width, caption_h),
                              border_bottom_left_radius=14, border_bottom_right_radius=14)
            screen.blit(caption_surface, (x, caption_y))

            name_surface = self.ui.font_small.render(img_info['filename'], True, self.CAPTION_TEXT)
            meta_surface = self.ui.font_micro.render(
                f"{img_info['size_mb']} MB  •  {img_info['resolution']}",
                True, self.CAPTION_TEXT_MUTED
            )
            screen.blit(name_surface, (x + 10, caption_y + 4))
            screen.blit(meta_surface, (x + 10, caption_y + 4 + name_surface.get_height()))
