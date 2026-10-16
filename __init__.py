"""
Hardware module - GPIO and Camera management
"""

from .hardware_gpio import GPIOController
from .hardware_camera import CameraManager

__all__ = ["GPIOController", "CameraManager"]
