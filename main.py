import os
import sys
import time
import logging
import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pi-led-api")

# Auto-configure system packages for virtualenv on Raspberry Pi
def _check_and_add_system_packages():
    if sys.prefix != sys.base_prefix:
        system_dist_packages = "/usr/lib/python3/dist-packages"
        if os.path.exists(system_dist_packages) and system_dist_packages not in sys.path:
            sys.path.append(system_dist_packages)
            logger.info(f"Dynamically appended system dist-packages to sys.path: {system_dist_packages}")

_check_and_add_system_packages()

# GPIO Import
GPIO_AVAILABLE = False
gpio_mode = "NONE"

try:
    from gpiozero import LED, PWMLED
    from gpiozero.pins.lgpio import LGPIOFactory
    import gpiozero
    gpiozero.Device.pin_factory = LGPIOFactory()
    GPIO_AVAILABLE = True
    gpio_mode = "GPIOZERO_LGPIO"
except Exception:
    try:
        import RPi.GPIO as GPIO
        GPIO_AVAILABLE = True
        gpio_mode = "RPI_GPIO"
    except Exception:
        try:
            import rpi_lgpio as GPIO
            GPIO_AVAILABLE = True
            gpio_mode = "RPI_LGPIO"
        except Exception:
            GPIO = None

class LEDController:
    def __init__(self):
        self.pins = {"red": 22, "yellow": 27, "green": 17}
        self.led_objects = {}
        self.current_state = "off"
        self._lock = threading.Lock()
        self._anim_thread = None
        self._stop_anim = False
        self._timer_thread = None

        if GPIO_AVAILABLE:
            try:
                if gpio_mode == "GPIOZERO_LGPIO":
                    for name, p in self.pins.items():
                        if name == "yellow":
                            try:
                                self.led_objects[name] = PWMLED(p)
                            except Exception:
                                self.led_objects[name] = LED(p)
                        else:
                            self.led_objects[name] = LED(p)
                    logger.info(f"Physical GPIO initialized via LGPIOFactory (Pins: {self.pins}).")
                elif gpio_mode in ("RPI_GPIO", "RPI_LGPIO") and globals().get('GPIO') is not None:
                    GPIO.setmode(GPIO.BCM)
                    GPIO.setwarnings(False)
                    for pin in self.pins.values():
                        GPIO.setup(pin, GPIO.OUT)
                    logger.info(f"Physical GPIO initialized via {gpio_mode} (Pins: {self.pins}).")
            except Exception as e:
                logger.error(f"Failed to init GPIO pins: {e}")
        else:
            logger.info("Running in Mock/Simulation mode.")

        # Startup sequence
        self.trigger_startup()

    def _stop_background_effects(self):
        """Stops active breathing/blinking threads safely. Must be called under lock."""
        self._stop_anim = True
        if self._anim_thread and self._anim_thread.is_alive() and threading.current_thread() != self._anim_thread:
            self._anim_thread.join(timeout=1.0)
        self._stop_anim = False

    def turn_all_off(self):
        """Turns all 3 LEDs off."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "off"
            self._set_raw_pin("red", 0)
            self._set_raw_pin("yellow", 0)
            self._set_raw_pin("green", 0)
            logger.info("All LEDs turned off.")

    def _set_raw_pin(self, pin_name: str, level: float):
        """Sets pin level (0.0 to 1.0)."""
        pin = self.pins.get(pin_name)
        if pin is None:
            return
        if GPIO_AVAILABLE:
            try:
                if gpio_mode == "GPIOZERO_LGPIO" and pin_name in self.led_objects:
                    obj = self.led_objects[pin_name]
                    if hasattr(obj, 'value'):
                        obj.value = max(0.0, min(1.0, level))
                    else:
                        if level > 0: obj.on()
                        else: obj.off()
                elif globals().get('GPIO') is not None:
                    GPIO.setup(pin, GPIO.OUT)
                    GPIO.output(pin, GPIO.HIGH if level > 0 else GPIO.LOW)
            except Exception as e:
                logger.error(f"GPIO output error on pin {pin}: {e}")
        else:
            logger.debug(f"[MOCK-GPIO] Pin {pin} ({pin_name.upper()}) -> Level {level:.2f}")

    def trigger_startup(self):
        """Flashes green LED 5 times."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "startup_complete"

            def _startup_worker():
                for _ in range(5):
                    if self._stop_anim:
                        break
                    self._set_raw_pin("green", 1.0)
                    time.sleep(0.2)
                    self._set_raw_pin("green", 0.0)
                    time.sleep(0.2)
                self.turn_all_off()

            self._anim_thread = threading.Thread(target=_startup_worker, daemon=True)
            self._anim_thread.start()
            logger.info("Startup blinking triggered.")

    def set_state_thinking(self):
        """Solid yellow."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "thinking_solid_yellow"
            self._set_raw_pin("yellow", 1.0)
            self._set_raw_pin("red", 0)
            self._set_raw_pin("green", 0)
            logger.info("State set to: Thinking (Solid Yellow)")

    def set_state_breathing_yellow(self):
        """Breathing yellow."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "breathing_yellow"
            self._set_raw_pin("red", 0)
            self._set_raw_pin("green", 0)

            def _breathing_worker():
                step = 0.05
                val = 0.1
                direction = 1
                while not self._stop_anim:
                    self._set_raw_pin("yellow", val)
                    time.sleep(0.05)
                    val += step * direction
                    if val >= 1.0:
                        val = 1.0
                        direction = -1
                    elif val <= 0.05:
                        val = 0.05
                        direction = 1

            self._anim_thread = threading.Thread(target=_breathing_worker, daemon=True)
            self._anim_thread.start()
            logger.info("State set to: Breathing Yellow")

    def set_state_restarting_yellow(self):
        """Blinking yellow."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "restarting_yellow_blink"
            self._set_raw_pin("red", 0)
            self._set_raw_pin("green", 0)

            def _restarting_worker():
                state = False
                while not self._stop_anim:
                    state = not state
                    self._set_raw_pin("yellow", 1.0 if state else 0.0)
                    time.sleep(0.25)

            self._anim_thread = threading.Thread(target=_restarting_worker, daemon=True)
            self._anim_thread.start()
            logger.info("State set to: Restarting (Blinking Yellow)")

    def set_state_error(self):
        """Solid red."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "solid_red_error"
            self._set_raw_pin("red", 1.0)
            self._set_raw_pin("yellow", 0)
            self._set_raw_pin("green", 0)
            logger.info("State set to: Error (Solid Red)")

    def set_state_success(self, duration: int = 300):
        """Solid green for duration seconds."""
        with self._lock:
            self._stop_background_effects()
            self.current_state = "success_solid_green"
            self._set_raw_pin("green", 1.0)
            self._set_raw_pin("red", 0)
            self._set_raw_pin("yellow", 0)

            def _timer_worker():
                for _ in range(duration):
                    if self._stop_anim:
                        break
                    time.sleep(1.0)
                with self._lock:
                    if self.current_state == "success_solid_green":
                        self._set_raw_pin("green", 0.0)
                        self.current_state = "off"
                        logger.info("Success green LED timer expired, turned off.")

            self._timer_thread = threading.Thread(target=_timer_worker, daemon=True)
            self._timer_thread.start()
            logger.info(f"State set to: Success (Solid Green for {duration}s)")

    def set_custom_led(self, color: str, action: str, value: float = 1.0, frequency: float = 1.0):
        """Allows direct control of custom actions on individual LEDs."""
        if color not in self.pins:
            raise ValueError(f"Invalid LED color: {color}")
        
        with self._lock:
            self._stop_background_effects()
            self.current_state = f"custom_{color}_{action}"
            
            # Turn others off first
            for other_color in self.pins:
                if other_color != color:
                    self._set_raw_pin(other_color, 0)

            if action == "off":
                self._set_raw_pin(color, 0)
                self.current_state = "off"
            elif action == "on":
                self._set_raw_pin(color, 1.0)
            elif action == "pwm":
                self._set_raw_pin(color, value)
            elif action == "blink":
                interval = 1.0 / (2.0 * frequency) if frequency > 0 else 0.5
                def _blink_worker():
                    state = False
                    while not self._stop_anim:
                        state = not state
                        self._set_raw_pin(color, value if state else 0.0)
                        time.sleep(interval)
                self._anim_thread = threading.Thread(target=_blink_worker, daemon=True)
                self._anim_thread.start()
            elif action == "breath":
                def _breath_worker():
                    step = 0.05
                    val = 0.0
                    direction = 1
                    sleep_time = 0.05 / frequency if frequency > 0 else 0.05
                    while not self._stop_anim:
                        self._set_raw_pin(color, val * value)
                        time.sleep(sleep_time)
                        val += step * direction
                        if val >= 1.0:
                            val = 1.0
                            direction = -1
                        elif val <= 0.0:
                            val = 0.0
                            direction = 1
                self._anim_thread = threading.Thread(target=_breath_worker, daemon=True)
                self._anim_thread.start()
            else:
                raise ValueError(f"Invalid custom action: {action}")


# Instantiate Global LED Controller
controller = LEDController()

# Instantiate FastAPI App
app = FastAPI(
    title="🍓 Raspberry Pi LED Control API",
    description="RESTful API to control Raspberry Pi physical indicator status lights.",
    version="1.0.0"
)

# Enable CORS for cross-platform integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class StateRequest(BaseModel):
    state: str = Field(..., description="System state to display: 'thinking', 'breathing', 'restarting', 'success', 'error', 'startup', 'off'")
    duration: Optional[int] = Field(300, description="Duration in seconds (only applicable for 'success' state)")

class LEDControlRequest(BaseModel):
    color: str = Field(..., description="Target LED color: 'red', 'yellow', 'green'")
    action: str = Field(..., description="Action: 'on', 'off', 'pwm', 'blink', 'breath'")
    value: Optional[float] = Field(1.0, ge=0.0, le=1.0, description="PWM level or brightness (0.0 to 1.0)")
    frequency: Optional[float] = Field(1.0, ge=0.1, le=10.0, description="Blinking or breathing frequency in Hz")

# Routes
@app.get("/")
def read_root():
    return {
        "message": "Welcome to Raspberry Pi LED Control API",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "hardware": {
            "gpio_available": GPIO_AVAILABLE,
            "mode": gpio_mode,
            "pins": controller.pins
        }
    }

@app.get("/api/status")
def get_status():
    return {
        "status": "ok",
        "current_state": controller.current_state,
        "hardware": {
            "gpio_available": GPIO_AVAILABLE,
            "mode": gpio_mode,
            "pins": controller.pins
        }
    }

@app.post("/api/state")
def set_state(req: StateRequest):
    state = req.state.strip().lower()
    if state == "thinking":
        controller.set_state_thinking()
    elif state == "breathing":
        controller.set_state_breathing_yellow()
    elif state == "restarting":
        controller.set_state_restarting_yellow()
    elif state == "error":
        controller.set_state_error()
    elif state == "success":
        controller.set_state_success(req.duration)
    elif state == "startup":
        controller.trigger_startup()
    elif state == "off":
        controller.turn_all_off()
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported state: '{req.state}'")
    
    return {"status": "success", "new_state": controller.current_state}

@app.post("/api/led")
def control_led(req: LEDControlRequest):
    color = req.color.strip().lower()
    action = req.action.strip().lower()
    
    if color not in controller.pins:
        raise HTTPException(status_code=400, detail=f"Unsupported LED color: '{req.color}'. Supported colors: {list(controller.pins.keys())}")
        
    try:
        controller.set_custom_led(color, action, req.value, req.frequency)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return {"status": "success", "new_state": controller.current_state}

@app.post("/api/off")
def turn_off():
    controller.turn_all_off()
    return {"status": "success", "new_state": controller.current_state}
