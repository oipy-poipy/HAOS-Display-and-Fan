from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PAGES = [
    {
        "name": "System",
        "lines": [
            "#{hostname}\t{clock}",
            "CPU\t{cpu_temp_c}°C",
            "RAM\t{mem_percent}%",
            "Disk\t{disk_percent}%",
            "Fan\t{fan_percent}% {fan_mode}",
        ],
    },
    {
        "name": "Network",
        "lines": [
            "#Network\t{clock}",
            "IP\t{ip}",
            "Up\t{uptime_short}",
            "Load\t{cpu_load_1m}",
        ],
    },
    {
        "name": "Home",
        "lines": [
            "#Home\t{clock}",
            "Out\t{ha:sensor.outdoor_temperature,weather.forecast_home@temperature,weather.home@temperature|1°C}",
            "Sky\t{ha:weather.forecast_home,weather.home}",
            "Hum\t{ha:sensor.outdoor_humidity,weather.forecast_home@humidity|0%}",
            "Wind\t{ha:weather.forecast_home@wind_speed,weather.home@wind_speed|0 km/h}",
        ],
    },
]

DEFAULT_CURVE = [
    {"temp_c": 45, "percent": 0},
    {"temp_c": 55, "percent": 35},
    {"temp_c": 65, "percent": 70},
    {"temp_c": 75, "percent": 100},
]


class ConfigError(ValueError):
    """Raised when add-on configuration cannot be parsed safely."""


@dataclass(frozen=True)
class DisplayPage:
    name: str
    lines: list[str]


@dataclass(frozen=True)
class FanCurvePoint:
    temp_c: float
    percent: int


@dataclass(frozen=True)
class AppConfig:
    log_level: str = "info"
    mock_hardware: bool = False
    device_name: str = "HA Pi Panel"
    mqtt_enabled: bool = True
    mqtt_base_topic: str = "ha_pi_panel"
    mqtt_discovery_prefix: str = "homeassistant"
    metrics_poll_seconds: int = 5
    ha_entity_poll_seconds: int = 10
    display_enabled: bool = True
    display_type: str = "ssd1306_128x64"
    display_i2c_device: str = "/dev/i2c-1"
    display_i2c_address: int = 0x3C
    display_width: int = 128
    display_height: int = 64
    display_rotate: int = 0
    display_contrast: int = 128
    display_invert: bool = False
    display_refresh_seconds: int = 2
    display_page_seconds: int = 6
    display_blank_when_idle: bool = False
    display_pages: list[DisplayPage] = field(default_factory=lambda: parse_display_pages(json.dumps(DEFAULT_PAGES)))
    fan_enabled: bool = True
    fan_control_method: str = "gpio_onoff"
    fan_gpiochip: str = "/dev/gpiochip0"
    fan_gpio_line: int = 18
    fan_active_high: bool = True
    fan_pwm_frequency_hz: int = 25000
    fan_min_percent: int = 25
    fan_kickstart_percent: int = 100
    fan_kickstart_seconds: int = 1
    fan_mode: str = "auto"
    fan_manual_percent: int = 50
    fan_curve: list[FanCurvePoint] = field(default_factory=lambda: parse_fan_curve(json.dumps(DEFAULT_CURVE)))
    fan_fail_safe_temp_c: int = 80
    fan_shutdown_behavior: str = "on"


def clamp(value: int | float, low: int, high: int) -> int:
    return max(low, min(high, int(round(value))))


def parse_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    raise ConfigError(f"{name} must be a boolean")


def parse_i2c_address(value: Any) -> int:
    if isinstance(value, int):
        address = value
    elif isinstance(value, str):
        address = int(value.strip(), 0)
    else:
        raise ConfigError("display_i2c_address must be an integer or hex string")
    if not 0x03 <= address <= 0x77:
        raise ConfigError("display_i2c_address must be a valid 7-bit I2C address")
    return address


def _load_json_array(raw: str, name: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{name} must be valid JSON") from exc
    if not isinstance(data, list):
        raise ConfigError(f"{name} must be a JSON array")
    if not all(isinstance(item, dict) for item in data):
        raise ConfigError(f"{name} must contain objects")
    return data


def parse_display_pages(raw: str | None) -> list[DisplayPage]:
    items = _load_json_array(raw or json.dumps(DEFAULT_PAGES), "display_pages_json")
    pages: list[DisplayPage] = []
    for index, item in enumerate(items):
        lines = item.get("lines", [])
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise ConfigError(f"display page {index} must contain a string lines array")
        name = str(item.get("name") or f"Page {index + 1}")
        pages.append(DisplayPage(name=name, lines=lines))
    if not pages:
        raise ConfigError("display_pages_json must contain at least one page")
    return pages


def parse_fan_curve(raw: str | None) -> list[FanCurvePoint]:
    items = _load_json_array(raw or json.dumps(DEFAULT_CURVE), "fan_curve_json")
    points: list[FanCurvePoint] = []
    for item in items:
        if "temp_c" not in item or "percent" not in item:
            raise ConfigError("fan_curve_json points need temp_c and percent")
        points.append(FanCurvePoint(temp_c=float(item["temp_c"]), percent=clamp(parse_int(item["percent"], "fan curve percent"), 0, 100)))
    if not points:
        raise ConfigError("fan_curve_json must contain at least one point")
    return sorted(points, key=lambda point: point.temp_c)


def _require_choice(value: str, name: str, choices: Iterable[str]) -> str:
    allowed = set(choices)
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(sorted(allowed))}")
    return value


def load_config(path: str | Path = "/data/options.json") -> AppConfig:
    options_path = Path(path)
    raw: dict[str, Any] = {}
    if options_path.exists():
        raw = json.loads(options_path.read_text(encoding="utf-8-sig"))

    log_level = _require_choice(str(raw.get("log_level", "info")).lower(), "log_level", ["trace", "debug", "info", "warning", "error"])
    display_type = _require_choice(str(raw.get("display_type", "ssd1306_128x64")), "display_type", ["ssd1306_128x64", "ssd1306_128x32", "sh1106_128x64"])
    fan_control_method = _require_choice(str(raw.get("fan_control_method", "gpio_onoff")), "fan_control_method", ["off", "gpio_onoff", "software_pwm", "sysfs_pwm"])
    fan_mode = _require_choice(str(raw.get("fan_mode", "auto")), "fan_mode", ["auto", "manual", "off"])
    shutdown_behavior = _require_choice(str(raw.get("fan_shutdown_behavior", "on")), "fan_shutdown_behavior", ["off", "on", "leave"])
    rotate = parse_int(raw.get("display_rotate", 0), "display_rotate")
    if rotate not in {0, 90, 180, 270}:
        raise ConfigError("display_rotate must be 0, 90, 180, or 270")

    return AppConfig(
        log_level=log_level,
        mock_hardware=parse_bool(raw.get("mock_hardware", False), "mock_hardware"),
        device_name=str(raw.get("device_name", "HA Pi Panel")),
        mqtt_enabled=parse_bool(raw.get("mqtt_enabled", True), "mqtt_enabled"),
        mqtt_base_topic=str(raw.get("mqtt_base_topic", "ha_pi_panel")).strip().strip("/") or "ha_pi_panel",
        mqtt_discovery_prefix=str(raw.get("mqtt_discovery_prefix", "homeassistant")).strip().strip("/") or "homeassistant",
        metrics_poll_seconds=clamp(parse_int(raw.get("metrics_poll_seconds", 5), "metrics_poll_seconds"), 1, 300),
        ha_entity_poll_seconds=clamp(parse_int(raw.get("ha_entity_poll_seconds", 10), "ha_entity_poll_seconds"), 1, 300),
        display_enabled=parse_bool(raw.get("display_enabled", True), "display_enabled"),
        display_type=display_type,
        display_i2c_device=str(raw.get("display_i2c_device", "/dev/i2c-1")),
        display_i2c_address=parse_i2c_address(raw.get("display_i2c_address", "0x3C")),
        display_width=clamp(parse_int(raw.get("display_width", 128), "display_width"), 1, 512),
        display_height=clamp(parse_int(raw.get("display_height", 64), "display_height"), 1, 512),
        display_rotate=rotate,
        display_contrast=clamp(parse_int(raw.get("display_contrast", 128), "display_contrast"), 0, 255),
        display_invert=parse_bool(raw.get("display_invert", False), "display_invert"),
        display_refresh_seconds=clamp(parse_int(raw.get("display_refresh_seconds", 2), "display_refresh_seconds"), 1, 300),
        display_page_seconds=clamp(parse_int(raw.get("display_page_seconds", 6), "display_page_seconds"), 1, 300),
        display_blank_when_idle=parse_bool(raw.get("display_blank_when_idle", False), "display_blank_when_idle"),
        display_pages=parse_display_pages(raw.get("display_pages_json")),
        fan_enabled=parse_bool(raw.get("fan_enabled", True), "fan_enabled"),
        fan_control_method=fan_control_method,
        fan_gpiochip=str(raw.get("fan_gpiochip", "/dev/gpiochip0")),
        fan_gpio_line=parse_int(raw.get("fan_gpio_line", 18), "fan_gpio_line"),
        fan_active_high=parse_bool(raw.get("fan_active_high", True), "fan_active_high"),
        fan_pwm_frequency_hz=clamp(parse_int(raw.get("fan_pwm_frequency_hz", 25000), "fan_pwm_frequency_hz"), 1, 50000),
        fan_min_percent=clamp(parse_int(raw.get("fan_min_percent", 25), "fan_min_percent"), 0, 100),
        fan_kickstart_percent=clamp(parse_int(raw.get("fan_kickstart_percent", 100), "fan_kickstart_percent"), 0, 100),
        fan_kickstart_seconds=clamp(parse_int(raw.get("fan_kickstart_seconds", 1), "fan_kickstart_seconds"), 0, 10),
        fan_mode=fan_mode,
        fan_manual_percent=clamp(parse_int(raw.get("fan_manual_percent", 50), "fan_manual_percent"), 0, 100),
        fan_curve=parse_fan_curve(raw.get("fan_curve_json")),
        fan_fail_safe_temp_c=parse_int(raw.get("fan_fail_safe_temp_c", 80), "fan_fail_safe_temp_c"),
        fan_shutdown_behavior=shutdown_behavior,
    )
