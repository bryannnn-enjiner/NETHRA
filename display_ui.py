# display/ui.py
import math
import time
import pygame


class UIHelper:
    """Helper untuk UI rendering"""

    STATUS_BAR_HEIGHT = 26
    FOOTER_HEIGHT = 56

    # Maps a DR classification label to a colors dict key, per clinical
    # severity convention: Normal=green, NPDR=orange (in-between), PDR=red.
    CLASS_COLOR_KEYS = {
        "NPDR": "class_orange",
        "Normal": "success_green",
        "PDR": "danger_red",
    }

    def __init__(self, width, height, colors):
        self.width = width
        self.height = height
        self.colors = colors

        # Load fonts
        self.font_title = pygame.font.SysFont("Arial", 40, bold=True)
        self.font_large = pygame.font.SysFont("Arial", 30, bold=True)
        self.font_normal = pygame.font.SysFont("Arial", 22)
        self.font_small = pygame.font.SysFont("Arial", 16)
        self.font_tiny = pygame.font.SysFont("Arial", 12)
        self.font_wordmark = pygame.font.SysFont("Arial", 15, bold=True)
        self.font_label = pygame.font.SysFont("Arial", 18, bold=True)
        self.font_micro = pygame.font.SysFont("Arial", 11)

    # ------------------------------------------------------------------
    # Basics
    # ------------------------------------------------------------------

    def draw_background(self, screen):
        """Draw background"""
        screen.fill(self.colors['bg_primary'])

    def draw_text_centered(self, screen, text, y, font=None, color=None):
        """Draw centered text"""
        if font is None:
            font = self.font_normal
        if color is None:
            color = self.colors['text_primary']

        surface = font.render(text, True, color)
        x = (self.width - surface.get_width()) // 2
        screen.blit(surface, (x, y))
        return surface

    def draw_text(self, screen, text, x, y, font=None, color=None):
        """Draw text at position"""
        if font is None:
            font = self.font_normal
        if color is None:
            color = self.colors['text_primary']

        surface = font.render(text, True, color)
        screen.blit(surface, (x, y))
        return surface

    # ------------------------------------------------------------------
    # Status bar (top): wordmark + online/offline badge
    # ------------------------------------------------------------------

    def draw_status_bar(self, screen, mode="online", title="EyeXaminer", show_title=True,
                         battery_percentage=None):
        """Draw the slim top status bar with wordmark, connection badge, and
        an optional phone-style battery icon (battery_percentage None = UPS
        HAT not detected, icon omitted)."""
        bar_h = self.STATUS_BAR_HEIGHT
        pygame.draw.rect(screen, self.colors['bg_card'], (0, 0, self.width, bar_h))

        if show_title:
            title_surface = self.font_wordmark.render(title, True, self.colors['text_primary'])
            screen.blit(title_surface, (12, (bar_h - title_surface.get_height()) // 2))

        # Online/offline badge, right aligned
        is_online = mode == "online"
        dot_color = self.colors['success_green'] if is_online else self.colors['danger_red']
        label = "Online" if is_online else "Offline"
        label_surface = self.font_micro.render(label, True, self.colors['text_muted'])

        dot_r = 4
        pad_right = 12
        label_x = self.width - pad_right - label_surface.get_width()
        dot_x = label_x - dot_r * 2 - 6
        cy = bar_h // 2

        pygame.draw.circle(screen, dot_color, (dot_x, cy), dot_r)
        screen.blit(label_surface, (label_x, cy - label_surface.get_height() // 2))

        if battery_percentage is not None:
            batt_w, batt_h = 30, 16
            batt_x = dot_x - dot_r - 14 - batt_w
            batt_y = cy - batt_h // 2
            self.draw_icon_battery(screen, batt_x, batt_y, battery_percentage, size=(batt_w, batt_h))
        else:
            # No UPS HAT battery detected - assume running on a USB power
            # adapter. A small hand-drawn plug/bolt icon didn't read clearly
            # at this size, so just label it with text instead.
            usb_surface = self.font_micro.render("USB", True, self.colors['text_muted'])
            usb_x = dot_x - dot_r - 14 - usb_surface.get_width()
            screen.blit(usb_surface, (usb_x, cy - usb_surface.get_height() // 2))

        return bar_h

    # ------------------------------------------------------------------
    # Camera preview card
    # ------------------------------------------------------------------

    def draw_camera_frame(self, screen, x, y, width, height, preview_surface=None,
                           state='live', show_reticle=True, status_text=None):
        """Draw the camera preview card.

        state: 'live' (renders preview_surface + reticle), 'loading'
        (camera present but no frame yet), or 'unavailable' (no camera
        detected / picamera2 failed to load).
        """
        rect = (x, y, width, height)
        pygame.draw.rect(screen, self.colors['bg_card'], rect, border_radius=14)

        if state == 'live' and preview_surface is not None:
            # Fit the full camera frame inside the card without cropping or
            # distorting its aspect ratio; letterbox with the card color.
            inner = pygame.Rect(x + 2, y + 2, width - 4, height - 4)
            src_w, src_h = preview_surface.get_size()
            scale = min(inner.width / src_w, inner.height / src_h)
            draw_w, draw_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
            scaled = pygame.transform.smoothscale(preview_surface, (draw_w, draw_h))
            draw_x = inner.x + (inner.width - draw_w) // 2
            draw_y = inner.y + (inner.height - draw_h) // 2
            screen.blit(scaled, (draw_x, draw_y))

            if show_reticle:
                self._draw_reticle(screen, x + width // 2, y + height // 2,
                                    min(draw_w, draw_h) // 3)

            border_color = self.colors['accent_blue']
        elif state == 'loading':
            msg_surface = self.font_small.render(status_text or "Starting camera...",
                                                   True, self.colors['text_muted'])
            msg_x = x + (width - msg_surface.get_width()) // 2
            msg_y = y + (height - msg_surface.get_height()) // 2
            screen.blit(msg_surface, (msg_x, msg_y))
            border_color = self.colors['bg_card']
        else:
            self._draw_icon_camera_off(screen, x + width // 2, y + height // 2 - 14, 30,
                                        self.colors['text_muted'])
            msg = status_text or "Camera Not Connected"
            msg_surface = self.font_small.render(msg, True, self.colors['text_muted'])
            msg_x = x + (width - msg_surface.get_width()) // 2
            msg_y = y + height // 2 + 22
            screen.blit(msg_surface, (msg_x, msg_y))
            border_color = self.colors['bg_card']

        pygame.draw.rect(screen, border_color, rect, 2, border_radius=14)

    def draw_focus_score(self, screen, score, x, y, width):
        """Small live sharpness readout in the top-right of the preview card -
        maximize this number while turning the lens's manual focus ring."""
        text = f"Focus: {score:.0f}"
        surface = self.font_micro.render(text, True, self.colors['text_muted'])
        pad_x, pad_y = 8, 4
        bg_w = surface.get_width() + pad_x * 2
        bg_h = surface.get_height() + pad_y * 2
        bg_x = x + width - bg_w - 8
        bg_y = y + 8

        bg_surface = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        pygame.draw.rect(bg_surface, (*self.colors['bg_card'], 200), (0, 0, bg_w, bg_h), border_radius=6)
        screen.blit(bg_surface, (bg_x, bg_y))
        screen.blit(surface, (bg_x + pad_x, bg_y + pad_y))

    def draw_flash_off_badge(self, screen, x, y):
        """Small top-left badge on the preview card, shown only when the
        capture flash has been manually disabled (hold the Gallery button
        on the main screen to toggle) - mirrors draw_focus_score's style,
        placed on the opposite corner."""
        text = "Flash Off"
        surface = self.font_micro.render(text, True, self.colors['warning_yellow'])
        pad_x, pad_y = 8, 4
        bg_w = surface.get_width() + pad_x * 2
        bg_h = surface.get_height() + pad_y * 2
        bg_x = x + 8
        bg_y = y + 8

        bg_surface = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        pygame.draw.rect(bg_surface, (*self.colors['bg_card'], 200), (0, 0, bg_w, bg_h), border_radius=6)
        screen.blit(bg_surface, (bg_x, bg_y))
        screen.blit(surface, (bg_x + pad_x, bg_y + pad_y))

    def _draw_reticle(self, screen, cx, cy, radius):
        """Subtle circular alignment guide + corner ticks, fundus-camera style.

        Draws straight onto `screen` (no per-frame full-size SRCALPHA
        surface) - that allocation was expensive enough at 20fps to be a
        real contributor to preview stutter on the framebuffer/X target.
        """
        guide_color = self.colors['accent_blue']
        ring_surface = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring_surface, (*guide_color, 90), (radius + 2, radius + 2), radius, 1)
        screen.blit(ring_surface, (cx - radius - 2, cy - radius - 2))

        tick = 10
        gap = 4
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            px = cx + sx * (radius + gap)
            py = cy + sy * (radius + gap)
            pygame.draw.line(screen, guide_color, (px, py), (px - sx * tick, py), 2)
            pygame.draw.line(screen, guide_color, (px, py), (px, py - sy * tick), 2)

    # ------------------------------------------------------------------
    # Footer action bar (mirrors the two physical buttons below the screen)
    # ------------------------------------------------------------------

    def draw_footer(self, screen, left_icon, left_label, right_icon, right_label):
        """Draw the flat footer strip with an icon+label per physical button"""
        y = self.height - self.FOOTER_HEIGHT
        pygame.draw.line(screen, self.colors['bg_card'], (0, y), (self.width, y), 1)

        half = self.width // 2
        self._draw_footer_action(screen, left_icon, left_label, 0, y, half)
        self._draw_footer_action(screen, right_icon, right_label, half, y, self.width - half)

        divider_x = half
        pygame.draw.line(screen, self.colors['bg_card'],
                          (divider_x, y + 10), (divider_x, self.height - 10), 1)

    def _draw_footer_action(self, screen, icon_name, label, x, y, width):
        cx = x + width // 2
        icon_cy = y + 18
        icon_fns = {
            'shutter': self._draw_icon_shutter,
            'gallery': self._draw_icon_gallery,
            'prev': lambda s, cx, cy, r, c: self._draw_icon_chevron(s, cx, cy, r, c, -1),
            'next': lambda s, cx, cy, r, c: self._draw_icon_chevron(s, cx, cy, r, c, 1),
        }
        icon_fn = icon_fns.get(icon_name)
        if icon_fn:
            icon_fn(screen, cx, icon_cy, 11, self.colors['accent_blue'])

        label_surface = self.font_label.render(label, True, self.colors['text_primary'])
        label_x = cx - label_surface.get_width() // 2
        label_y = y + 32
        screen.blit(label_surface, (label_x, label_y))

    # ------------------------------------------------------------------
    # Icons (hand-drawn with pygame primitives, no external assets)
    # ------------------------------------------------------------------

    def _draw_icon_shutter(self, screen, cx, cy, r, color):
        pygame.draw.circle(screen, color, (cx, cy), r, 2)
        pygame.draw.circle(screen, color, (cx, cy), max(2, r - 5))

    def _draw_icon_chevron(self, screen, cx, cy, size, color, direction):
        """direction: -1 points left "<" (prev), 1 points right ">" (next).
        The vertex (single middle point) is on the side the chevron points to."""
        w, h = size * 0.7, size
        points = [
            (cx - direction * w * 0.4, cy - h * 0.5),
            (cx + direction * w * 0.4, cy),
            (cx - direction * w * 0.4, cy + h * 0.5),
        ]
        pygame.draw.lines(screen, color, False, points, 3)

    def _draw_icon_gallery(self, screen, cx, cy, size, color):
        """2x2 grid of rounded squares"""
        gap = max(2, size // 8)
        sq = (size - gap) / 2
        x0 = cx - size / 2
        y0 = cy - size / 2
        for row in range(2):
            for col in range(2):
                rx = x0 + col * (sq + gap)
                ry = y0 + row * (sq + gap)
                pygame.draw.rect(screen, color, (rx, ry, sq, sq), border_radius=2)

    def _draw_icon_camera_off(self, screen, cx, cy, size, color):
        body_w, body_h = size, int(size * 0.72)
        body_rect = (cx - body_w // 2, cy - body_h // 2, body_w, body_h)
        pygame.draw.rect(screen, color, body_rect, 2, border_radius=6)

        bump_w = size // 3
        pygame.draw.rect(screen, color,
                          (cx - bump_w // 2, cy - body_h // 2 - 6, bump_w, 6), border_radius=2)

        lens_r = int(body_h * 0.28)
        pygame.draw.circle(screen, color, (cx, cy), lens_r, 2)

        diag = int(size * 0.85)
        pygame.draw.line(screen, self.colors['danger_red'],
                          (cx - diag // 2, cy - diag // 2),
                          (cx + diag // 2, cy + diag // 2), 3)

    def _lerp_color(self, c1, c2, t):
        t = max(0.0, min(1.0, t))
        return tuple(round(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

    def battery_color(self, percentage):
        """Continuous green -> orange -> red gradient (not banded steps):
        100% is full green, 50% is orange, 0% is red, smoothly blended
        in between so the colour shifts gradually as it drains."""
        green = self.colors['success_green']
        orange = self.colors['class_orange']
        red = self.colors['danger_red']
        if percentage >= 50:
            return self._lerp_color(orange, green, (percentage - 50) / 50)
        return self._lerp_color(red, orange, percentage / 50)

    def draw_icon_battery(self, screen, x, y, percentage, size=(18, 9)):
        """Phone-status-bar-style battery icon: outline + proportional fill
        + nub, colour-coded by level. No numeric percentage shown - just
        how full it looks, like a phone."""
        w, h = size
        nub_w, nub_h = 2, max(2, round(h * 0.5))

        fill_color = self.battery_color(percentage)

        pygame.draw.rect(screen, self.colors['text_muted'], (x, y, w, h), 1, border_radius=2)
        nub_rect = (x + w, y + (h - nub_h) // 2, nub_w, nub_h)
        pygame.draw.rect(screen, self.colors['text_muted'], nub_rect, border_radius=1)

        pad = 2
        fill_w = max(0, round((w - pad * 2) * (percentage / 100)))
        if fill_w > 0:
            pygame.draw.rect(screen, fill_color, (x + pad, y + pad, fill_w, h - pad * 2), border_radius=1)

    def draw_icon_wifi(self, screen, x, y, connected, size=14):
        color = self.colors['success_green'] if connected else self.colors['text_muted']
        cx, cy = x + size // 2, y + size
        for i, r in enumerate((size * 0.35, size * 0.6, size * 0.85)):
            start_angle = math.radians(215)
            end_angle = math.radians(325)
            rect = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
            width = 2 if connected or i == 0 else 1
            pygame.draw.arc(screen, color, rect, start_angle, end_angle, width)
        pygame.draw.circle(screen, color, (cx, cy), 2)

    # ------------------------------------------------------------------
    # Toast / status message card
    # ------------------------------------------------------------------

    def draw_toast(self, screen, message, color=None, icon='check'):
        """Draw a small floating status card near the bottom of the preview area"""
        if color is None:
            color = self.colors['success_green']

        text_surface = self.font_normal.render(message, True, self.colors['text_primary'])
        pad_x, pad_y = 18, 10
        icon_space = 26
        card_w = text_surface.get_width() + pad_x * 2 + icon_space
        card_h = text_surface.get_height() + pad_y * 2

        card_x = (self.width - card_w) // 2
        card_y = self.height - self.FOOTER_HEIGHT - card_h - 14

        card_surface = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
        pygame.draw.rect(card_surface, (*self.colors['bg_card'], 235),
                          (0, 0, card_w, card_h), border_radius=10)
        pygame.draw.rect(card_surface, (*color, 255), (0, 0, card_w, card_h), 2, border_radius=10)
        screen.blit(card_surface, (card_x, card_y))

        icon_cx = card_x + pad_x + 6
        icon_cy = card_y + card_h // 2
        if icon == 'check':
            self._draw_icon_check(screen, icon_cx, icon_cy, 8, color)

        screen.blit(text_surface, (card_x + pad_x + icon_space, card_y + pad_y))

    def _draw_icon_check(self, screen, cx, cy, r, color):
        pygame.draw.circle(screen, color, (cx, cy), r, 2)
        points = [(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.4), (cx + r * 0.5, cy - r * 0.4)]
        pygame.draw.lines(screen, color, False, points, 2)

    # ------------------------------------------------------------------
    # DR classification: analyzing spinner + result card
    # ------------------------------------------------------------------

    def classification_color(self, class_name):
        """RGB color for a classification label (falls back to muted grey)."""
        key = self.CLASS_COLOR_KEYS.get(class_name)
        return self.colors.get(key, self.colors['text_muted'])

    def draw_spinner_overlay(self, screen, x, y, width, height, message="Analyzing image..."):
        """Dim the given rect and draw a rotating arc + status text over it,
        used while classification inference is running in the background."""
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(overlay, (*self.colors['bg_primary'], 215), (0, 0, width, height),
                          border_radius=14)
        screen.blit(overlay, (x, y))

        cx, cy = x + width // 2, y + height // 2 - 10
        radius = 22
        angle = (time.time() * 260) % 360
        rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
        pygame.draw.arc(screen, self.colors['accent_blue'], rect,
                         math.radians(angle), math.radians(angle + 260), 4)

        msg_surface = self.font_small.render(message, True, self.colors['text_muted'])
        msg_x = cx - msg_surface.get_width() // 2
        msg_y = cy + radius + 16
        screen.blit(msg_surface, (msg_x, msg_y))

    def draw_classification_result(self, screen, class_name, confidence):
        """Floating result card near the bottom of the preview area, colored
        by clinical severity (Normal=green, NPDR=orange, PDR=red)."""
        color = self.classification_color(class_name)
        label = class_name or "Unknown"
        pct_text = f"{confidence * 100:.0f}% confidence"

        label_surface = self.font_large.render(label, True, color)
        pct_surface = self.font_small.render(pct_text, True, self.colors['text_muted'])

        pad_x, pad_y, gap = 22, 12, 4
        card_w = max(label_surface.get_width(), pct_surface.get_width()) + pad_x * 2
        card_h = label_surface.get_height() + pct_surface.get_height() + pad_y * 2 + gap

        card_x = (self.width - card_w) // 2
        card_y = self.height - self.FOOTER_HEIGHT - card_h - 14

        card_surface = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
        pygame.draw.rect(card_surface, (*self.colors['bg_card'], 240), (0, 0, card_w, card_h),
                          border_radius=12)
        pygame.draw.rect(card_surface, (*color, 255), (0, 0, card_w, card_h), 2, border_radius=12)
        screen.blit(card_surface, (card_x, card_y))

        screen.blit(label_surface,
                    (card_x + (card_w - label_surface.get_width()) // 2, card_y + pad_y))
        screen.blit(pct_surface,
                    (card_x + (card_w - pct_surface.get_width()) // 2,
                     card_y + pad_y + label_surface.get_height() + gap))

    # ------------------------------------------------------------------
    # Misc (kept for gallery screen / image frames)
    # ------------------------------------------------------------------

    def draw_hold_progress(self, screen, progress, y):
        """Growing progress bar shown while a gallery button is held past a
        tap (no label - just the bar itself)."""
        bar_w, bar_h = 160, 6
        x = (self.width - bar_w) // 2
        pygame.draw.rect(screen, self.colors['bg_card'], (x, y, bar_w, bar_h), border_radius=3)
        fill_w = round(bar_w * progress)
        if fill_w > 0:
            pygame.draw.rect(screen, self.colors['accent_blue'], (x, y, fill_w, bar_h), border_radius=3)

    def draw_delete_confirm_dialog(self, screen, selection):
        """Modal: 'Delete this image?' with Yes/No options. Left button
        moves the selection cursor, right button confirms it - separate
        from the hold gesture that opens this dialog in the first place."""
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pygame.draw.rect(overlay, (*self.colors['bg_primary'], 210), (0, 0, self.width, self.height))
        screen.blit(overlay, (0, 0))

        dialog_w, dialog_h = 260, 110
        x = (self.width - dialog_w) // 2
        y = (self.height - dialog_h) // 2

        pygame.draw.rect(screen, self.colors['bg_card'], (x, y, dialog_w, dialog_h), border_radius=14)
        pygame.draw.rect(screen, self.colors['accent_blue'], (x, y, dialog_w, dialog_h), 2, border_radius=14)

        title_surface = self.font_normal.render("Delete this image?", True, self.colors['text_primary'])
        screen.blit(title_surface, (x + (dialog_w - title_surface.get_width()) // 2, y + 16))

        opt_w, opt_h, gap = 90, 34, 16
        total_w = opt_w * 2 + gap
        opt_y = y + dialog_h - opt_h - 16
        no_x = x + (dialog_w - total_w) // 2
        yes_x = no_x + opt_w + gap

        self._draw_dialog_option(screen, no_x, opt_y, opt_w, opt_h, "No", selection == 'no')
        self._draw_dialog_option(screen, yes_x, opt_y, opt_w, opt_h, "Yes", selection == 'yes')

    def _draw_dialog_option(self, screen, x, y, w, h, label, active):
        if active:
            fill = self.colors['danger_red'] if label == "Yes" else self.colors['accent_blue']
            text_color = (255, 255, 255)
            pygame.draw.rect(screen, fill, (x, y, w, h), border_radius=8)
        else:
            text_color = self.colors['text_muted']
            pygame.draw.rect(screen, self.colors['bg_card'], (x, y, w, h), border_radius=8)
            pygame.draw.rect(screen, self.colors['text_muted'], (x, y, w, h), 1, border_radius=8)

        label_surface = self.font_label.render(label, True, text_color)
        screen.blit(label_surface, (x + (w - label_surface.get_width()) // 2,
                                     y + (h - label_surface.get_height()) // 2))

    def draw_pill(self, screen, text, x, y, color=None, text_color=None, font=None):
        """Draw a small rounded pill badge, returns its width"""
        if color is None:
            color = self.colors['bg_card']
        if text_color is None:
            text_color = self.colors['text_primary']
        if font is None:
            font = self.font_small

        text_surface = font.render(text, True, text_color)
        pad_x, pad_y = 10, 4
        w = text_surface.get_width() + pad_x * 2
        h = text_surface.get_height() + pad_y * 2

        pygame.draw.rect(screen, color, (x, y, w, h), border_radius=h // 2)
        screen.blit(text_surface, (x + pad_x, y + pad_y))
        return w

    def draw_image_frame(self, screen, image_surface, x, y, width, height):
        """Draw image in frame"""
        pygame.draw.rect(screen, self.colors['accent_blue'], (x, y, width, height), 2, border_radius=10)
        if image_surface:
            scaled_img = pygame.transform.smoothscale(image_surface, (width - 4, height - 4))
            screen.blit(scaled_img, (x + 2, y + 2))
