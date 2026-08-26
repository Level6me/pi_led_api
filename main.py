"""
🍓 Raspberry Pi LED Control API (v2.4 - Clean Edition)
Apple-Style RESTful & WebSocket API with:
1. CIE 1931 / Gamma 2.2 Human Eye Light Perception & Smooth Sinusoidal Breathing
2. Dynamic Custom Patterns Store & Timeline Runner (data/patterns.json)
3. Smart Timers & Gradual Fade-Out Engine (POST /api/timer)
4. Dynamic Hardware Pin Remapping & Active Polarity Config (data/hardware.json)
5. Audit Log CSV / JSON Export & Multi-dimensional Filtering
6. Local High-Speed OAuth2 JWT & Dynamic Device Tokens
"""

import os
import io
import csv
import math
import time
import json
import base64
import hmac
import hashlib
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from typing import Dict, Any, List, Optional, Union

import psutil

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, Header, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ==================== 日志与目录初始化 ====================
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler("logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pi-led-api")

# ==================== 认证密钥与存储路径 ====================
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin888").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "pi_led_jwt_secret_key_2026").strip()
JWT_EXPIRATION_SECONDS = int(os.getenv("JWT_EXPIRATION_SECONDS", "86400"))

TOKEN_STORE_PATH = "data/tokens.json"
HARDWARE_STORE_PATH = "data/hardware.json"
PATTERNS_STORE_PATH = "data/patterns.json"

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def b64url_decode(s: str) -> bytes:
    pad = len(s) % 4
    if pad: s += "=" * (4 - pad)
    return base64.urlsafe_b64decode(s)

def create_jwt_token(payload: dict, secret: str = JWT_SECRET) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h_b64 = b64url_encode(json.dumps(header).encode())
    p_b64 = b64url_encode(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    s_b64 = b64url_encode(sig)
    return f"{h_b64}.{p_b64}.{s_b64}"

def verify_jwt_token(token: str, secret: str = JWT_SECRET) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    sig = hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if b64url_encode(sig) != parts[2]:
        raise ValueError("JWT signature verification failed")
    payload = json.loads(b64url_decode(parts[1]).decode())
    if "exp" in payload and payload["exp"] < time.time():
        raise ValueError("JWT token has expired")
    return payload

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/oauth/token", auto_error=False)

# ==================== 硬件配置与自定义动效存储 ====================
def load_hardware_config() -> Dict[str, Any]:
    default_hw = {
        "pins": {"red": 22, "yellow": 27, "green": 17},
        "active_high": True,
        "gamma_correction": True,
        "gamma_value": 2.2
    }
    if os.path.exists(HARDWARE_STORE_PATH):
        try:
            with open(HARDWARE_STORE_PATH, "r", encoding="utf-8") as f:
                default_hw.update(json.load(f))
        except Exception:
            pass
    return default_hw

def save_hardware_config(conf: Dict[str, Any]):
    try:
        with open(HARDWARE_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(conf, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write {HARDWARE_STORE_PATH}: {e}")

def load_patterns_store() -> Dict[str, Any]:
    if os.path.exists(PATTERNS_STORE_PATH):
        try:
            with open(PATTERNS_STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_patterns_store(patterns: Dict[str, Any]):
    try:
        with open(PATTERNS_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write {PATTERNS_STORE_PATH}: {e}")

# ==================== 动态与静态 Token 令牌存储 ====================
def load_dynamic_tokens() -> Dict[str, Dict[str, Any]]:
    if os.path.exists(TOKEN_STORE_PATH):
        try:
            with open(TOKEN_STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {TOKEN_STORE_PATH}: {e}")
    return {}

def save_dynamic_tokens(tokens: Dict[str, Dict[str, Any]]):
    try:
        with open(TOKEN_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write {TOKEN_STORE_PATH}: {e}")

def parse_static_tokens() -> Dict[str, str]:
    token_map: Dict[str, str] = {}
    raw_tokens = os.getenv("API_TOKENS", "").strip()
    if raw_tokens:
        if raw_tokens.startswith("{") and raw_tokens.endswith("}"):
            try:
                token_map = json.loads(raw_tokens)
            except Exception:
                pass
        else:
            for pair in raw_tokens.split(","):
                parts = pair.split(":", 1)
                if len(parts) == 2:
                    token_map[parts[0].strip()] = parts[1].strip()
                elif len(parts) == 1 and parts[0].strip():
                    token_map[parts[0].strip()] = f"设备_{parts[0].strip()[:4]}"

    single_token = os.getenv("API_TOKEN", "").strip()
    if single_token and single_token not in token_map:
        token_map[single_token] = "默认主控客户端"

    return token_map

def get_all_valid_tokens() -> Dict[str, str]:
    combined = parse_static_tokens()
    dyn = load_dynamic_tokens()
    for item in dyn.values():
        tok = item.get("token")
        name = item.get("device_name", "动态设备")
        exp = item.get("expires_at")
        if tok:
            if exp and exp < time.time():
                continue
            combined[tok] = name
    return combined

def mask_token(token: str) -> str:
    if not token: return "***"
    if len(token) <= 6: return "***"
    return f"{token[:3]}****{token[-3:]}"

# ==================== 审计调用与统计系统 ====================
class AuditLogger:
    def __init__(self, max_memory_logs: int = 500):
        self.logs = deque(maxlen=max_memory_logs)
        self.log_file = "logs/audit.log"
        self._file_logger = logging.getLogger("pi-led-audit")
        self._file_logger.setLevel(logging.INFO)
        
        handler = RotatingFileHandler(self.log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        if not self._file_logger.handlers:
            self._file_logger.addHandler(handler)

    def record(
        self,
        device_name: str,
        token_used: Optional[str],
        client_ip: str,
        user_agent: str,
        method: str,
        endpoint: str,
        payload: Any,
        status_code: int,
        state_from: str,
        state_to: str,
        error_msg: Optional[str] = None
    ) -> Dict[str, Any]:
        entry = {
            "id": f"log_{int(time.time() * 1000)}_{len(self.logs) % 1000:03d}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "unix_time": time.time(),
            "device_name": device_name,
            "token_masked": mask_token(token_used) if token_used else None,
            "client_ip": client_ip,
            "user_agent": user_agent or "Unknown",
            "endpoint": f"{method} {endpoint}",
            "payload": payload,
            "status_code": status_code,
            "success": status_code < 400,
            "state_from": state_from,
            "state_to": state_to,
            "error": error_msg
        }
        self.logs.appendleft(entry)
        try:
            self._file_logger.info(json.dumps(entry, ensure_ascii=False))
        except Exception:
            pass
        return entry

    def get_logs(self, limit: int = 80, device: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        result = []
        for item in self.logs:
            if device and device.lower() not in item["device_name"].lower():
                continue
            if status == "success" and not item["success"]:
                continue
            if status == "error" and item["success"]:
                continue
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def get_stats_summary(self) -> Dict[str, Any]:
        total = len(self.logs)
        success_cnt = sum(1 for l in self.logs if l["success"])
        fail_cnt = total - success_cnt
        
        device_counts: Dict[str, int] = {}
        state_counts: Dict[str, int] = {}
        hourly_map: Dict[str, int] = {}

        now_hour = int(time.time() // 3600)
        for i in range(23, -1, -1):
            h_str = time.strftime("%H:00", time.localtime((now_hour - i) * 3600))
            hourly_map[h_str] = 0

        for l in self.logs:
            dev = l["device_name"]
            device_counts[dev] = device_counts.get(dev, 0) + 1

            st = l["state_to"]
            state_counts[st] = state_counts.get(st, 0) + 1

            h = time.strftime("%H:00", time.localtime(l["unix_time"]))
            if h in hourly_map:
                hourly_map[h] += 1

        pi_temp = None
        try:
            if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    pi_temp = round(float(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass

        return {
            "total_calls": total,
            "success_calls": success_cnt,
            "failed_calls": fail_cnt,
            "success_rate": round((success_cnt / total * 100) if total > 0 else 100, 1),
            "device_distribution": device_counts,
            "state_distribution": state_counts,
            "hourly_timeline": [{"hour": k, "count": v} for k, v in hourly_map.items()],
            "system_metrics": {
                "cpu_percent": psutil.cpu_percent(),
                "ram_percent": psutil.virtual_memory().percent,
                "temp_c": pi_temp,
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
        }

    def clear(self):
        self.logs.clear()

audit_logger = AuditLogger()

# ==================== GPIO 硬件与控制器 ====================
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

class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        dead = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.add(connection)
        for dead_conn in dead:
            self.active_connections.discard(dead_conn)

ws_manager = ConnectionManager()

# ==================== 智能倒计时引擎 ====================
class SmartTimerState:
    def __init__(self):
        self.active: bool = False
        self.color: Optional[str] = None
        self.preset_state: Optional[str] = None
        self.total_duration: int = 0
        self.remaining_seconds: int = 0
        self.fade_out_seconds: int = 5
        self.task: Optional[asyncio.Task] = None

smart_timer = SmartTimerState()

# ==================== AsyncLEDController 核心控制器 ====================
class AsyncLEDController:
    def __init__(self):
        self.hw_config = load_hardware_config()
        self.pins: Dict[str, int] = self.hw_config.get("pins", {"red": 22, "yellow": 27, "green": 17})
        self.active_high: bool = self.hw_config.get("active_high", True)
        self.gamma_enabled: bool = self.hw_config.get("gamma_correction", True)
        self.gamma_value: float = self.hw_config.get("gamma_value", 2.2)

        self.led_objects = {}
        self.current_state = "off"
        self.channel_states: Dict[str, Dict[str, Any]] = {
            "red": {"action": "off", "value": 0.0, "frequency": 1.0},
            "yellow": {"action": "off", "value": 0.0, "frequency": 1.0},
            "green": {"action": "off", "value": 0.0, "frequency": 1.0}
        }
        self._anim_tasks: Dict[str, asyncio.Task] = {}
        self._global_task: Optional[asyncio.Task] = None

        self._init_gpio()

    def _init_gpio(self):
        self.led_objects.clear()
        if GPIO_AVAILABLE and gpio_mode == "GPIOZERO_LGPIO":
            for name, p in self.pins.items():
                try:
                    self.led_objects[name] = PWMLED(p, active_high=self.active_high, initial_value=0.0)
                except Exception:
                    self.led_objects[name] = LED(p, active_high=self.active_high, initial_value=False)
                self._set_raw_pin(name, 0.0)
            logger.info(f"Physical GPIO initialized (Pins: {self.pins}, ActiveHigh: {self.active_high}). All pins reset to LOW.")
        elif GPIO_AVAILABLE and globals().get("GPIO") is not None:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                for p in self.pins.values():
                    GPIO.setup(p, GPIO.OUT)
                    GPIO.output(p, GPIO.HIGH if not self.active_high else GPIO.LOW)
            except Exception as e:
                logger.error(f"GPIO init error: {e}")

    def rebind_hardware(self, new_conf: Dict[str, Any]):
        self.cancel_all_tasks()
        for obj in self.led_objects.values():
            try: obj.close()
            except Exception: pass
        self.hw_config = new_conf
        self.pins = new_conf.get("pins", {"red": 22, "yellow": 27, "green": 17})
        self.active_high = new_conf.get("active_high", True)
        self.gamma_enabled = new_conf.get("gamma_correction", True)
        self.gamma_value = new_conf.get("gamma_value", 2.2)
        save_hardware_config(new_conf)
        self._init_gpio()

    def _apply_gamma(self, level: float) -> float:
        """CIE 1931 / Gamma 2.2 视觉感知亮度曲线校正"""
        if not self.gamma_enabled or self.gamma_value <= 1.0:
            return level
        return math.pow(max(0.0, min(1.0, level)), self.gamma_value)

    def _set_raw_pin(self, pin_name: str, level: float):
        pin = self.pins.get(pin_name)
        if pin is None: return
        raw_level = max(0.0, min(1.0, float(level)))
        calibrated_level = self._apply_gamma(raw_level)

        if GPIO_AVAILABLE:
            try:
                if gpio_mode == "GPIOZERO_LGPIO" and pin_name in self.led_objects:
                    obj = self.led_objects[pin_name]
                    if hasattr(obj, "value"):
                        obj.value = calibrated_level
                    else:
                        if calibrated_level > 0: obj.on()
                        else: obj.off()
                elif globals().get("GPIO") is not None:
                    GPIO.setup(pin, GPIO.OUT)
                    out_val = GPIO.HIGH if calibrated_level > 0 else GPIO.LOW
                    if not self.active_high:
                        out_val = GPIO.LOW if calibrated_level > 0 else GPIO.HIGH
                    GPIO.output(pin, out_val)
            except Exception as e:
                logger.error(f"GPIO output error on pin {pin}: {e}")

    def cancel_task(self, key: str):
        if key in self._anim_tasks:
            t = self._anim_tasks.pop(key)
            if not t.done(): t.cancel()

    def cancel_all_tasks(self):
        if self._global_task and not self._global_task.done():
            self._global_task.cancel()
            self._global_task = None
        for key, t in list(self._anim_tasks.items()):
            if not t.done(): t.cancel()
        self._anim_tasks.clear()

        if smart_timer.active and smart_timer.task and not smart_timer.task.done():
            smart_timer.task.cancel()
            smart_timer.active = False

    def get_snapshot(self) -> Dict[str, Any]:
        all_tokens = get_all_valid_tokens()
        return {
            "status": "ok",
            "current_state": self.current_state,
            "channels": self.channel_states,
            "hardware": {
                "gpio_available": GPIO_AVAILABLE,
                "mode": gpio_mode,
                "pins": self.pins,
                "active_high": self.active_high,
                "gamma_correction": self.gamma_enabled,
                "gamma_value": self.gamma_value
            },
            "smart_timer": {
                "active": smart_timer.active,
                "remaining_seconds": smart_timer.remaining_seconds,
                "total_duration": smart_timer.total_duration,
                "target": smart_timer.color or smart_timer.preset_state
            },
            "auth": {
                "oauth2_enabled": True,
                "token_required": bool(all_tokens or ADMIN_PASSWORD),
                "registered_devices_count": len(all_tokens)
            },
            "timestamp": time.time()
        }

    async def broadcast(self):
        await ws_manager.broadcast({"type": "state_update", "data": self.get_snapshot()})

    async def turn_all_off(self):
        self.cancel_all_tasks()
        self.current_state = "off"
        for c in self.pins:
            self._set_raw_pin(c, 0.0)
            self.channel_states[c] = {"action": "off", "value": 0.0, "frequency": 1.0}
        logger.info("All LEDs turned off.")
        await self.broadcast()

    async def trigger_startup(self):
        self.cancel_all_tasks()
        self.current_state = "startup_flashing_green"
        for c in self.pins:
            self._set_raw_pin(c, 0.0)
            self.channel_states[c] = {"action": "off", "value": 0.0, "frequency": 1.0}

        async def _startup():
            try:
                for _ in range(5):
                    self._set_raw_pin("green", 1.0)
                    self.channel_states["green"]["value"] = 1.0
                    self.channel_states["green"]["action"] = "on"
                    await self.broadcast()
                    await asyncio.sleep(0.18)
                    self._set_raw_pin("green", 0.0)
                    self.channel_states["green"]["value"] = 0.0
                    self.channel_states["green"]["action"] = "off"
                    await self.broadcast()
                    await asyncio.sleep(0.18)
                await self.turn_all_off()
            except asyncio.CancelledError:
                pass

        self._global_task = asyncio.create_task(_startup())

    async def set_state(self, state: str, duration: int = 300):
        self.cancel_all_tasks()
        state = state.strip().lower()

        if state == "off":
            await self.turn_all_off()

        elif state == "startup":
            await self.trigger_startup()

        elif state == "thinking":
            self.current_state = "thinking_solid_yellow"
            for c in self.pins:
                self._set_raw_pin(c, 1.0 if c == "yellow" else 0.0)
                self.channel_states[c] = {"action": "on" if c == "yellow" else "off", "value": 1.0 if c == "yellow" else 0.0, "frequency": 1.0}
            logger.info("System state set to: Thinking (Solid Yellow)")
            await self.broadcast()

        elif state == "breathing":
            self.current_state = "breathing_yellow"
            for c in self.pins:
                if c != "yellow":
                    self._set_raw_pin(c, 0.0)
                    self.channel_states[c] = {"action": "off", "value": 0.0, "frequency": 1.0}
            self.channel_states["yellow"] = {"action": "breath", "value": 1.0, "frequency": 1.0}

            async def _smooth_breath():
                t = 0.0
                step = 0.06
                try:
                    while True:
                        val = 0.04 + 0.96 * ((math.sin(t) + 1.0) / 2.0)
                        self._set_raw_pin("yellow", val)
                        self.channel_states["yellow"]["value"] = round(val, 2)
                        t += step
                        await asyncio.sleep(0.04)
                except asyncio.CancelledError:
                    pass

            self._global_task = asyncio.create_task(_smooth_breath())
            logger.info("System state set to: Breathing (Smooth Sine Yellow)")
            await self.broadcast()

        elif state == "restarting":
            self.current_state = "restarting_yellow_blink"
            for c in self.pins:
                if c != "yellow":
                    self._set_raw_pin(c, 0.0)
                    self.channel_states[c] = {"action": "off", "value": 0.0, "frequency": 1.0}
            self.channel_states["yellow"] = {"action": "blink", "value": 1.0, "frequency": 2.0}

            async def _blink():
                st = False
                try:
                    while True:
                        st = not st
                        self._set_raw_pin("yellow", 1.0 if st else 0.0)
                        self.channel_states["yellow"]["value"] = 1.0 if st else 0.0
                        await asyncio.sleep(0.25)
                except asyncio.CancelledError:
                    pass

            self._global_task = asyncio.create_task(_blink())
            logger.info("System state set to: Restarting (Blinking Yellow)")
            await self.broadcast()

        elif state == "error":
            self.current_state = "solid_red_error"
            for c in self.pins:
                self._set_raw_pin(c, 1.0 if c == "red" else 0.0)
                self.channel_states[c] = {"action": "on" if c == "red" else "off", "value": 1.0 if c == "red" else 0.0, "frequency": 1.0}
            logger.info("System state set to: Error (Solid Red)")
            await self.broadcast()

        elif state == "success":
            self.current_state = "success_solid_green"
            for c in self.pins:
                self._set_raw_pin(c, 1.0 if c == "green" else 0.0)
                self.channel_states[c] = {"action": "on" if c == "green" else "off", "value": 1.0 if c == "green" else 0.0, "frequency": 1.0}
            logger.info(f"System state set to: Success (Solid Green for {duration}s)")
            await self.broadcast()

            async def _success_timer():
                try:
                    await asyncio.sleep(duration)
                    if self.current_state == "success_solid_green":
                        await self.turn_all_off()
                except asyncio.CancelledError:
                    pass

            self._global_task = asyncio.create_task(_success_timer())
        else:
            raise ValueError(f"Unsupported state: {state}")

    async def set_channel(self, color: str, action: str, value: float = 1.0, frequency: float = 1.0, exclusive: bool = False):
        if color not in self.pins:
            raise ValueError(f"Invalid color: {color}")
        
        action = action.strip().lower()
        value = max(0.0, min(1.0, float(value)))
        frequency = max(0.1, min(10.0, float(frequency)))

        if exclusive:
            self.cancel_all_tasks()
            for other in self.pins:
                if other != color:
                    self._set_raw_pin(other, 0.0)
                    self.channel_states[other] = {"action": "off", "value": 0.0, "frequency": 1.0}
        else:
            self.cancel_task(color)
            if self._global_task and not self._global_task.done():
                self._global_task.cancel()
                self._global_task = None

        self.current_state = f"channel_{color}_{action}"
        self.channel_states[color] = {"action": action, "value": value, "frequency": frequency}

        if action == "off":
            self._set_raw_pin(color, 0.0)
            self.channel_states[color]["value"] = 0.0
            await self.broadcast()

        elif action in ("on", "pwm"):
            self._set_raw_pin(color, value if action == "pwm" else 1.0)
            self.channel_states[color]["value"] = value if action == "pwm" else 1.0
            await self.broadcast()

        elif action == "blink":
            interval = 1.0 / (2.0 * frequency)

            async def _blink():
                st = False
                try:
                    while True:
                        st = not st
                        lvl = value if st else 0.0
                        self._set_raw_pin(color, lvl)
                        self.channel_states[color]["value"] = lvl
                        await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    pass

            self._anim_tasks[color] = asyncio.create_task(_blink())
            await self.broadcast()

        elif action == "breath":
            async def _breath_ch():
                t = 0.0
                step = 0.08 * frequency
                try:
                    while True:
                        val = 0.04 + (value - 0.04) * ((math.sin(t) + 1.0) / 2.0)
                        self._set_raw_pin(color, val)
                        self.channel_states[color]["value"] = round(val, 2)
                        t += step
                        await asyncio.sleep(0.04)
                except asyncio.CancelledError:
                    pass

            self._anim_tasks[color] = asyncio.create_task(_breath_ch())
            await self.broadcast()
        else:
            raise ValueError(f"Unknown action: {action}")

    async def play_pattern(self, name: str, frames: List[Dict[str, Any]], repeat: int = 1):
        self.cancel_all_tasks()
        self.current_state = f"pattern_{name}"

        async def _pattern_runner():
            try:
                for _ in range(repeat):
                    for frame in frames:
                        dur = float(frame.get("duration", 0.2))
                        for c in self.pins:
                            if c in frame:
                                val = float(frame[c])
                                self._set_raw_pin(c, val)
                                self.channel_states[c] = {"action": "on" if val > 0 else "off", "value": val, "frequency": 1.0}
                        await self.broadcast()
                        await asyncio.sleep(dur)
                await self.turn_all_off()
            except asyncio.CancelledError:
                pass

        self._global_task = asyncio.create_task(_pattern_runner())
        await self.broadcast()

    async def start_smart_timer(self, color: str, duration_sec: int, fade_out_sec: int = 5):
        """智能倒计时渐暗关灯引擎"""
        self.cancel_all_tasks()
        duration_sec = max(5, duration_sec)
        fade_out_sec = min(fade_out_sec, duration_sec // 2)

        smart_timer.active = True
        smart_timer.color = color
        smart_timer.total_duration = duration_sec
        smart_timer.remaining_seconds = duration_sec
        smart_timer.fade_out_seconds = fade_out_sec

        await self.set_channel(color, "on", 1.0, exclusive=True)

        async def _timer_worker():
            try:
                while smart_timer.remaining_seconds > 0:
                    await asyncio.sleep(1.0)
                    smart_timer.remaining_seconds -= 1
                    
                    if smart_timer.remaining_seconds <= fade_out_sec and fade_out_sec > 0:
                        progress = smart_timer.remaining_seconds / float(fade_out_sec)
                        self._set_raw_pin(color, max(0.05, progress))
                        self.channel_states[color]["value"] = round(progress, 2)
                    
                    await self.broadcast()

                smart_timer.active = False
                await self.turn_all_off()
            except asyncio.CancelledError:
                smart_timer.active = False

        smart_timer.task = asyncio.create_task(_timer_worker())
        await self.broadcast()

controller = AsyncLEDController()

# ==================== FastAPI 初始化 ====================
async def lifespan(app: FastAPI):
    await controller.trigger_startup()
    yield
    await controller.turn_all_off()

app = FastAPI(
    title="🍓 Raspberry Pi LED Control API",
    description="Apple-Style RESTful & WebSocket API with Custom Patterns, Smart Timers, Gamma 2.2 Correction, Tokens & Logs Export.",
    version="2.4.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "public")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ==================== 统一鉴权依赖 ====================
class CallerContext:
    def __init__(self, device_name: str, token: Optional[str], client_ip: str, user_agent: str, auth_type: str = "Token"):
        self.device_name = device_name
        self.token = token
        self.client_ip = client_ip
        self.user_agent = user_agent
        self.auth_type = auth_type

def identify_caller(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
) -> CallerContext:
    client_ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("user-agent", "Unknown")
    all_tokens = get_all_valid_tokens()

    raw_token = bearer_token
    if not raw_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1].strip()

    if raw_token:
        try:
            jwt_data = verify_jwt_token(raw_token)
            device_name = jwt_data.get("device") or f"OAuth2用户 ({jwt_data.get('sub', 'Admin')})"
            return CallerContext(device_name=device_name, token=raw_token, client_ip=client_ip, user_agent=ua, auth_type="OAuth2-JWT")
        except Exception:
            pass

    extracted_token = x_api_key or token or raw_token

    if not all_tokens and not ADMIN_PASSWORD:
        return CallerContext(device_name="匿名访问者", token=None, client_ip=client_ip, user_agent=ua, auth_type="None")

    if extracted_token and extracted_token in all_tokens:
        device_name = all_tokens[extracted_token]
        return CallerContext(device_name=device_name, token=extracted_token, client_ip=client_ip, user_agent=ua, auth_type="Device-Token")

    audit_logger.record(
        device_name="未授权客户端",
        token_used=extracted_token,
        client_ip=client_ip,
        user_agent=ua,
        method=request.method,
        endpoint=request.url.path,
        payload=None,
        status_code=401,
        state_from=controller.current_state,
        state_to=controller.current_state,
        error_msg="Unauthorized: Invalid or missing token"
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未授权访问：请提供有效 Token 或进行登录",
        headers={"WWW-Authenticate": "Bearer"}
    )

# ==================== 请求体数据模型 ====================
class StateRequest(BaseModel):
    state: str = Field(..., description="预设状态名称 (thinking, breathing, restarting, success, error, startup, off)")
    duration: int = Field(300, description="持续秒数 (用于 success/error 自动归位)")

class ChannelRequest(BaseModel):
    color: str = Field(..., description="通道颜色 (red, yellow, green)")
    action: str = Field(..., description="动作类型 (on, off, pwm, blink, breath)")
    value: float = Field(1.0, description="亮度值 (0.0 到 1.0)")
    frequency: float = Field(1.0, description="闪烁或呼吸频率 (Hz)")
    exclusive: bool = Field(False, description="是否独占 (熄灭其它通道)")

class PatternFrame(BaseModel):
    red: float = 0.0
    yellow: float = 0.0
    green: float = 0.0
    duration: float = 0.2

class PatternRequest(BaseModel):
    name: Optional[str] = "custom_pattern"
    title: Optional[str] = None
    frames: Optional[List[PatternFrame]] = None
    repeat: int = Field(1, description="循环执行次数")

class TimerRequest(BaseModel):
    color: str = Field("green", description="点亮的指示灯颜色 (red, yellow, green)")
    duration_sec: int = Field(60, description="倒计时总时长 (秒)")
    fade_out_sec: int = Field(5, description="结束前渐暗时长 (秒)")

class HardwareConfigRequest(BaseModel):
    pins: Dict[str, int] = Field(..., description="BCM 编码引脚分配")
    active_high: bool = Field(True, description="是否高电平有效 (共阴极)")
    gamma_correction: bool = Field(True, description="是否启用 Gamma 2.2 视觉平滑校正")
    gamma_value: float = Field(2.2, description="Gamma 幂指数值")

class CreateTokenRequest(BaseModel):
    device_name: str = Field(..., description="设备或调用来源名称")
    custom_token: Optional[str] = Field(None, description="自定义 Token")
    expires_days: int = Field(0, description="有效期天数 (0 为永久)")

# ==================== API 核心端点 ====================

@app.get("/", response_class=HTMLResponse)
@app.head("/")
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return "<h1>Pi LED Controller v2.4</h1>"

@app.get("/api/status")
async def get_status():
    return controller.get_snapshot()

@app.post("/api/state")
async def set_state(req: StateRequest, request: Request, caller: CallerContext = Depends(identify_caller)):
    state_from = controller.current_state
    try:
        await controller.set_state(req.state, req.duration)
        log_entry = audit_logger.record(
            device_name=caller.device_name,
            token_used=caller.token,
            client_ip=caller.client_ip,
            user_agent=caller.user_agent,
            method="POST",
            endpoint="/api/state",
            payload=req.model_dump(),
            status_code=200,
            state_from=state_from,
            state_to=controller.current_state
        )
        await ws_manager.broadcast({"type": "new_log", "data": log_entry})
        return controller.get_snapshot()
    except Exception as e:
        audit_logger.record(
            device_name=caller.device_name,
            token_used=caller.token,
            client_ip=caller.client_ip,
            user_agent=caller.user_agent,
            method="POST",
            endpoint="/api/state",
            payload=req.model_dump(),
            status_code=400,
            state_from=state_from,
            state_to=controller.current_state,
            error_msg=str(e)
        )
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/led")
async def set_led(req: ChannelRequest, request: Request, caller: CallerContext = Depends(identify_caller)):
    state_from = controller.current_state
    try:
        await controller.set_channel(req.color, req.action, req.value, req.frequency, req.exclusive)
        log_entry = audit_logger.record(
            device_name=caller.device_name,
            token_used=caller.token,
            client_ip=caller.client_ip,
            user_agent=caller.user_agent,
            method="POST",
            endpoint="/api/led",
            payload=req.model_dump(),
            status_code=200,
            state_from=state_from,
            state_to=controller.current_state
        )
        await ws_manager.broadcast({"type": "new_log", "data": log_entry})
        return controller.get_snapshot()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/off")
async def turn_off(request: Request, caller: CallerContext = Depends(identify_caller)):
    state_from = controller.current_state
    await controller.turn_all_off()
    log_entry = audit_logger.record(
        device_name=caller.device_name,
        token_used=caller.token,
        client_ip=caller.client_ip,
        user_agent=caller.user_agent,
        method="POST",
        endpoint="/api/off",
        payload=None,
        status_code=200,
        state_from=state_from,
        state_to="off"
    )
    await ws_manager.broadcast({"type": "new_log", "data": log_entry})
    return controller.get_snapshot()

# ==================== 智能倒计时引擎端点 ====================
@app.post("/api/timer")
async def set_timer(req: TimerRequest, caller: CallerContext = Depends(identify_caller)):
    await controller.start_smart_timer(req.color, req.duration_sec, req.fade_out_sec)
    return {
        "status": "success",
        "message": f"Smart timer started for {req.color} ({req.duration_sec}s with {req.fade_out_sec}s fade-out)",
        "timer": controller.get_snapshot()["smart_timer"]
    }

@app.delete("/api/timer")
async def cancel_timer(caller: CallerContext = Depends(identify_caller)):
    await controller.turn_all_off()
    return {"status": "success", "message": "Smart timer canceled"}

# ==================== 自定义动效库管理 ====================
@app.get("/api/patterns")
async def list_patterns():
    patterns = load_patterns_store()
    return {"status": "ok", "patterns": patterns}

@app.post("/api/patterns")
async def save_pattern(req: PatternRequest, caller: CallerContext = Depends(identify_caller)):
    if not req.name or not req.frames:
        raise HTTPException(status_code=400, detail="Pattern name and frames are required")
    patterns = load_patterns_store()
    patterns[req.name] = {
        "name": req.name,
        "title": req.title or req.name,
        "repeat": req.repeat,
        "frames": [f.model_dump() for f in req.frames]
    }
    save_patterns_store(patterns)
    return {"status": "success", "message": f"Pattern '{req.name}' saved successfully", "pattern": patterns[req.name]}

@app.delete("/api/patterns/{name}")
async def delete_pattern(name: str, caller: CallerContext = Depends(identify_caller)):
    patterns = load_patterns_store()
    if name not in patterns:
        raise HTTPException(status_code=404, detail="Pattern not found")
    del patterns[name]
    save_patterns_store(patterns)
    return {"status": "success", "message": f"Pattern '{name}' deleted"}

@app.post("/api/pattern")
async def run_pattern(req: PatternRequest, caller: CallerContext = Depends(identify_caller)):
    frames_to_run = []
    repeat_cnt = req.repeat or 1
    pattern_name = req.name or "custom"

    if req.frames:
        frames_to_run = [f.model_dump() for f in req.frames]
    elif req.name:
        store = load_patterns_store()
        if req.name in store:
            p_data = store[req.name]
            frames_to_run = p_data.get("frames", [])
            repeat_cnt = req.repeat or p_data.get("repeat", 1)
        else:
            raise HTTPException(status_code=404, detail=f"Pattern '{req.name}' not found")
    else:
        raise HTTPException(status_code=400, detail="Provide either pattern name or frames")

    await controller.play_pattern(pattern_name, frames_to_run, repeat_cnt)
    return controller.get_snapshot()

# ==================== 硬件引脚热重载配置 ====================
@app.get("/api/hardware/config")
async def get_hardware_config():
    return {
        "status": "ok",
        "config": controller.hw_config,
        "available_mode": gpio_mode
    }

@app.post("/api/hardware/config")
async def update_hardware_config(req: HardwareConfigRequest, caller: CallerContext = Depends(identify_caller)):
    new_conf = req.model_dump()
    controller.rebind_hardware(new_conf)
    return {
        "status": "success",
        "message": "Hardware configuration updated & GPIO reloaded",
        "config": new_conf
    }

# ==================== 审计日志与数据导出 ====================
@app.get("/api/logs")
async def get_logs(limit: int = 80, device: Optional[str] = None, status: Optional[str] = None):
    return {"status": "ok", "logs": audit_logger.get_logs(limit=limit, device=device, status=status)}

@app.delete("/api/logs")
async def clear_logs(caller: CallerContext = Depends(identify_caller)):
    audit_logger.clear()
    return {"status": "ok", "message": "Audit logs cleared"}

@app.get("/api/logs/export")
async def export_logs(format: str = Query("csv", regex="^(csv|json)$")):
    logs = audit_logger.get_logs(limit=500)
    if format == "json":
        return JSONResponse(
            content=logs,
            headers={"Content-Disposition": f"attachment; filename=pi_led_audit_logs_{int(time.time())}.json"}
        )
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "时间", "设备/客户端", "客户端IP", "请求端点", "状态码", "结果", "初始状态", "目标状态", "错误信息"])
    for l in logs:
        writer.writerow([
            l.get("id"),
            l.get("timestamp"),
            l.get("device_name"),
            l.get("client_ip"),
            l.get("endpoint"),
            l.get("status_code"),
            "成功" if l.get("success") else "失败",
            l.get("state_from"),
            l.get("state_to"),
            l.get("error") or ""
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pi_led_audit_logs_{int(time.time())}.csv"}
    )

@app.get("/api/stats/summary")
async def get_stats_summary():
    return audit_logger.get_stats_summary()

# ==================== Token 动态管理 ====================
@app.get("/api/tokens")
async def list_tokens():
    static_toks = parse_static_tokens()
    dyn_toks = load_dynamic_tokens()
    result = []
    for tok, name in static_toks.items():
        result.append({
            "id": f"static_{abs(hash(tok)) % 10000}",
            "device_name": name,
            "token_masked": mask_token(tok),
            "type": "static",
            "created_at": "配置文件",
            "expires_at": None,
            "can_delete": False
        })
    for k, item in dyn_toks.items():
        result.append({
            "id": item["id"],
            "device_name": item["device_name"],
            "token_masked": mask_token(item["token"]),
            "type": "dynamic",
            "created_at": item.get("created_at", "未知"),
            "expires_at": item.get("expires_at"),
            "can_delete": True
        })
    return {"status": "ok", "tokens": result}

@app.post("/api/tokens/create")
async def create_token(req: CreateTokenRequest, caller: CallerContext = Depends(identify_caller)):
    tokens = load_dynamic_tokens()
    token_str = req.custom_token.strip() if req.custom_token else f"tok_{secrets_token_hex(16)}"
    tok_id = f"tok_{int(time.time())}_{secrets_token_hex(3)}"
    expires_at = (time.time() + req.expires_days * 86400) if req.expires_days > 0 else None

    token_obj = {
        "id": tok_id,
        "device_name": req.device_name.strip(),
        "token": token_str,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "expires_at": expires_at,
        "created_by": caller.device_name
    }
    tokens[tok_id] = token_obj
    save_dynamic_tokens(tokens)
    return {
        "status": "success",
        "id": tok_id,
        "token": token_str,
        "device_name": req.device_name,
        "created_at": token_obj["created_at"],
        "expires_at": expires_at
    }

def secrets_token_hex(n: int = 16) -> str:
    import secrets
    return secrets.token_hex(n)

@app.delete("/api/tokens/{token_id}")
async def delete_token(token_id: str, caller: CallerContext = Depends(identify_caller)):
    tokens = load_dynamic_tokens()
    if token_id not in tokens:
        raise HTTPException(status_code=404, detail="Token 未找到或不可删除")
    del tokens[token_id]
    save_dynamic_tokens(tokens)
    return {"status": "success", "message": f"Token {token_id} 已成功撤销"}

# ==================== OAuth2 登录与凭据 ====================
@app.post("/api/oauth/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username.strip()
    password = form_data.password.strip()

    # 1. 管理员账号密码匹配
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        payload = {
            "sub": username,
            "device": "管理员控制台 (admin)",
            "role": "admin",
            "exp": time.time() + JWT_EXPIRATION_SECONDS
        }
        token = create_jwt_token(payload)
        return {"access_token": token, "token_type": "bearer", "device_name": "管理员控制台 (admin)"}

    # 2. 设备 Token 快捷登录
    valid_tokens = get_all_valid_tokens()
    if password in valid_tokens or username in valid_tokens:
        tok_val = password if password in valid_tokens else username
        dev_name = valid_tokens[tok_val]
        payload = {
            "sub": dev_name,
            "device": dev_name,
            "role": "device",
            "exp": time.time() + JWT_EXPIRATION_SECONDS * 30
        }
        token = create_jwt_token(payload)
        return {"access_token": token, "token_type": "bearer", "device_name": dev_name}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码/令牌错误",
        headers={"WWW-Authenticate": "Bearer"}
    )

@app.get("/api/oauth/userinfo")
async def get_current_user_info(caller: CallerContext = Depends(identify_caller)):
    return {
        "device_name": caller.device_name,
        "client_ip": caller.client_ip,
        "auth_type": caller.auth_type,
        "user_agent": caller.user_agent
    }

# ==================== WebSocket 实时广播 ====================
@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({"type": "state_update", "data": controller.get_snapshot()})
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                if cmd.get("action") == "ping":
                    await websocket.send_json({"type": "pong", "time": time.time()})
            except Exception:
                pass
    except (WebSocketDisconnect, Exception):
        ws_manager.disconnect(websocket)
