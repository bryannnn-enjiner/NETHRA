# hardware/gpio.py
import time
from gpiozero import Button, LED

try:
    from rpi_ws281x import PixelStrip, Color
except ImportError:
    PixelStrip = None
    Color = None


class GPIOController:
    """Control GPIO pins untuk buttons, IR illumination, dan RGB capture flash.

    - Buttons: physical Kiri/Kanan buttons under the screen.
    - IR LEDs: two always-on illumination LEDs (on from init to cleanup).
    - RGB flash: WS2812B ring (WCMCU-2812B-12) driven over the rp1_ws281x_pwm
      kernel module (Pi 5's RP1 needs this instead of the classic PWM/DMA
      register access older Pis use). Fires a brief full-white pulse on
      capture. Degrades gracefully (no-op) if the module/hardware isn't
      available, same pattern as CameraManager/ClassifierManager.
    """

    def __init__(self, btn_capture_pin, btn_menu_pin, ir_led_pins, rgb_config):
        self.btn_capture = Button(btn_capture_pin, pull_up=True, bounce_time=0.1)
        self.btn_menu = Button(btn_menu_pin, pull_up=True, bounce_time=0.1)

        self.ir_leds = [LED(pin) for pin in ir_led_pins]
        self.ir_led_on()

        self.flash_duration = rgb_config['duration']
        self.flash_available = False
        self.flash_error = None
        self._strip = None
        self._init_flash(rgb_config)

    def _init_flash(self, rgb_config):
        if PixelStrip is None:
            self.flash_error = "rpi_ws281x not installed"
            return
        try:
            self._strip = PixelStrip(
                rgb_config['led_count'],
                rgb_config['gpio_pin'],
                freq_hz=800000,
                dma=rgb_config['dma_channel'],
                invert=False,
                brightness=rgb_config['brightness'],
                channel=0,
            )
            self._strip.begin()
            self.flash_available = True
        except Exception as e:
            self.flash_error = str(e)
            self._strip = None

    def ir_led_on(self):
        """Turn on both IR illumination LEDs"""
        for led in self.ir_leds:
            led.on()

    def ir_led_off(self):
        """Turn off both IR illumination LEDs"""
        for led in self.ir_leds:
            led.off()

    def _set_flash_pixels(self, color):
        for i in range(self._strip.numPixels()):
            self._strip.setPixelColor(i, color)
        self._strip.show()

    def flash_on(self):
        """Turn the flash ring on immediately (non-blocking). Callers bracket
        this tightly around the actual shutter/exposure call so the flash is
        genuinely lit while the sensor captures - a fixed sleep()-based pulse
        fired before the capture call would go dark before the photo is
        actually taken."""
        if not self.flash_available:
            return
        self._set_flash_pixels(Color(255, 255, 255))

    def flash_off(self):
        """Turn the flash ring off immediately (non-blocking)."""
        if not self.flash_available:
            return
        self._set_flash_pixels(Color(0, 0, 0))

    def flash_pulse(self, duration=None):
        """Blocking on-wait-off pulse, for standalone testing outside a real
        capture (where nothing else defines how long the flash should stay lit)."""
        if not self.flash_available:
            return
        duration = self.flash_duration if duration is None else duration
        self.flash_on()
        time.sleep(duration)
        self.flash_off()

    def flash_led_off(self):
        """Alias kept for backward compatibility with existing callers."""
        self.flash_off()

    def is_capture_pressed(self):
        """Check if capture button pressed"""
        return self.btn_capture.is_pressed

    def is_menu_pressed(self):
        """Check if menu button pressed"""
        return self.btn_menu.is_pressed

    def is_both_pressed(self):
        """Check if both buttons pressed together"""
        return self.btn_capture.is_pressed and self.btn_menu.is_pressed

    def cleanup(self):
        """Cleanup GPIO on exit"""
        self.ir_led_off()
        self.flash_led_off()
        self.btn_capture.close()
        self.btn_menu.close()
