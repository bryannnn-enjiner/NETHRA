# hardware/hardware_battery.py
import threading
import time

try:
    import smbus2 as smbus
except ImportError:
    smbus = None


class _Reg:
    CONFIG = 0x00
    SHUNT_VOLTAGE = 0x01
    BUS_VOLTAGE = 0x02
    POWER = 0x03
    CURRENT = 0x04
    CALIBRATION = 0x05


class BatteryMonitor:
    """Reads battery charge over I2C from the INA219 power monitor on the
    Waveshare UPS HAT (B).

    Calibration/register values match Waveshare's own INA219 demo driver
    exactly (0.1 ohm shunt -> cal=4096, current_lsb=100uA, power_lsb=2mW).
    Percentage assumes the 2S li-ion pack this HAT is designed for
    (bus voltage range ~6.0-8.4V).

    Connectivity is polled in a background thread and cached, same pattern
    as NetworkManager: UI code calls get_percentage() every render frame,
    so it must return instantly instead of hitting I2C each time.
    """

    I2C_BUS = 1
    I2C_ADDRESS = 0x43
    POLL_INTERVAL = 5  # seconds between background reads

    CAL_VALUE = 4096
    CURRENT_LSB = 0.1   # mA per bit
    POWER_LSB = 0.002   # W per bit

    # 32V bus range, /8 gain (320mV shunt range), 12bit/32-sample ADC, shunt+bus continuous
    _CONFIG_VALUE = (0x01 << 13) | (0x03 << 11) | (0x0D << 7) | (0x0D << 3) | 0x07

    def __init__(self, i2c_bus=None, address=None):
        self.available = False
        self.error = None
        self._bus = None
        self._address = self.I2C_ADDRESS if address is None else address

        self._lock = threading.Lock()
        self._percentage = None
        self._charging = None

        self._init_sensor(self.I2C_BUS if i2c_bus is None else i2c_bus)

    def _init_sensor(self, i2c_bus):
        if smbus is None:
            self.error = "smbus2 not installed"
            return
        try:
            self._bus = smbus.SMBus(i2c_bus)
            self._write_register(_Reg.CALIBRATION, self.CAL_VALUE)
            self._write_register(_Reg.CONFIG, self._CONFIG_VALUE)
            self._read_register(_Reg.BUS_VOLTAGE)  # confirms the chip actually answers
        except Exception as e:
            self.error = str(e)
            return

        self.available = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _read_register(self, reg):
        data = self._bus.read_i2c_block_data(self._address, reg, 2)
        return (data[0] << 8) | data[1]

    def _write_register(self, reg, value):
        payload = [(value >> 8) & 0xFF, value & 0xFF]
        self._bus.write_i2c_block_data(self._address, reg, payload)

    def _read_bus_voltage(self):
        self._write_register(_Reg.CALIBRATION, self.CAL_VALUE)
        self._read_register(_Reg.BUS_VOLTAGE)
        raw = self._read_register(_Reg.BUS_VOLTAGE)
        return (raw >> 3) * 0.004

    def _read_current_ma(self):
        raw = self._read_register(_Reg.CURRENT)
        if raw > 32767:
            raw -= 65535
        return raw * self.CURRENT_LSB

    def _read_once(self):
        bus_voltage = self._read_bus_voltage()
        current_ma = self._read_current_ma()

        percentage = (bus_voltage - 6) / 2.4 * 100
        percentage = max(0.0, min(100.0, percentage))
        charging = current_ma > 0
        return percentage, charging

    def _monitor_loop(self):
        while True:
            try:
                percentage, charging = self._read_once()
                with self._lock:
                    self._percentage = percentage
                    self._charging = charging
            except Exception:
                pass
            time.sleep(self.POLL_INTERVAL)

    def get_percentage(self):
        """Instant, non-blocking: last known battery percentage (0-100), or
        None if the UPS HAT isn't detected."""
        with self._lock:
            return self._percentage

    def is_charging(self):
        with self._lock:
            return self._charging


# Singleton instance, mirroring config.wifi_network.network_manager
battery_monitor = BatteryMonitor()
