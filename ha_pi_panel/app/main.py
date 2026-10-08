from __future__ import annotations

import logging
import os
import signal
import sys
import time
from typing import Any

from . import __version__
from .config import AppConfig, load_config
from .display import create_display
from .fan import create_fan_controller
from .ha_api import HomeAssistantApi
from .hardware import device_exists, log_hardware_probe
from .mqtt_discovery import MqttManager
from .render import extract_ha_entities, render_page
from .system_metrics import architecture, collect_metrics


LOG_LEVELS = {"trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


def setup_logging(level: str) -> None:
    logging.basicConfig(level=LOG_LEVELS.get(level, logging.INFO), format="%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


class RuntimeState:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.display_enabled = config.display_enabled and not config.display_blank_when_idle
        self.fan_manual_percent = config.fan_manual_percent
        self.fan_mode = config.fan_mode
        self.stop = False


def main() -> int:
    config = load_config(os.environ.get("OPTIONS_PATH", "/data/options.json"))
    setup_logging(config.log_level)
    logger = logging.getLogger("ha_pi_panel")
    logger.info("HA Pi Panel version %s", __version__)
    logger.info("Architecture: %s", architecture())
    logger.info("Mock hardware: %s", config.mock_hardware)
    log_hardware_probe(config.display_i2c_device, config.fan_gpiochip)
    if not device_exists(config.display_i2c_device) and not config.mock_hardware:
        logger.warning("%s is missing. Enable I2C on Home Assistant OS and restart.", config.display_i2c_device)
    if not device_exists(config.fan_gpiochip) and not config.mock_hardware:
        logger.warning("%s is missing. Fan control will run degraded if selected.", config.fan_gpiochip)

    state = RuntimeState(config)
    display = create_display(config)
    fan = create_fan_controller(config)
    ha_api = HomeAssistantApi()
    logger.info("Home Assistant API proxy: %s", "available" if ha_api.available else "missing SUPERVISOR_TOKEN")

    def set_fan_percent(percent: int) -> None:
        state.fan_manual_percent = percent
        state.fan_mode = "manual"
        fan.mode = "manual"
        fan.requested_percent = percent

    def set_display_enabled(enabled: bool) -> None:
        state.display_enabled = enabled
        if not enabled:
            display.blank()

    def set_fan_mode(mode: str) -> None:
        state.fan_mode = mode
        fan.mode = mode

    mqtt = MqttManager(config, set_fan_percent, set_display_enabled, set_fan_mode)
    mqtt.connect()
    logger.info("MQTT connection status: %s", "enabled" if mqtt.enabled else "disabled")

    ha_entities = extract_ha_entities(config.display_pages)
    last_metrics_at = 0.0
    last_display_at = 0.0
    last_page_advance_at = time.monotonic()
    last_ha_warm_at = 0.0
    page_index = 0
    metrics = collect_metrics()
    logger.info("Host %s reachable at %s", metrics.hostname, metrics.ip)
    if ha_entities:
        logger.info("Display pages reference Home Assistant entities: %s", ", ".join(sorted(ha_entities)))

    def request_stop(signum: int, frame: Any) -> None:
        state.stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        while not state.stop:
            now = time.monotonic()
            if now - last_metrics_at >= config.metrics_poll_seconds:
                metrics = collect_metrics()
                fan.mode = state.fan_mode
                target = state.fan_manual_percent if state.fan_mode == "manual" else fan.calculate_target(metrics.cpu_temp_c)
                fan.apply(target)
                mqtt.publish_state(build_state(config, state, display.status, fan, metrics))
                last_metrics_at = now

            if ha_entities and now - last_ha_warm_at >= config.ha_entity_poll_seconds:
                ha_api.warm_cache(ha_entities)
                last_ha_warm_at = now

            if now - last_page_advance_at >= config.display_page_seconds:
                page_index = (page_index + 1) % len(config.display_pages)
                last_page_advance_at = now

            if state.display_enabled and now - last_display_at >= config.display_refresh_seconds:
                tokens = metrics.as_tokens()
                tokens.update({"fan_percent": str(fan.requested_percent), "fan_mode": state.fan_mode, "display_status": display.status})
                rendered = render_page(config.display_pages[page_index], config.display_width, config.display_height, config.display_rotate, tokens, ha_api.get_state)
                display.show(rendered.image, rendered.text_lines)
                last_display_at = now

            time.sleep(0.2)
    finally:
        logger.info("Shutting down")
        try:
            display.close()
        finally:
            fan.close()
            mqtt.close()
    return 0


def build_state(config: AppConfig, state: RuntimeState, display_status: str, fan: Any, metrics: Any) -> dict[str, Any]:
    fan_fault = config.fan_control_method != "off" and fan.backend.backend_state == "off_backend"
    hardware_fault = "ON" if display_status == "fault" or fan_fault else "OFF"
    return {
        "cpu_temp_c": metrics.cpu_temp_c,
        "cpu_load_1m": metrics.cpu_load_1m,
        "mem_percent": metrics.mem_percent,
        "disk_percent": metrics.disk_percent,
        "uptime": metrics.uptime,
        "uptime_seconds": metrics.uptime_seconds,
        "fan_requested_percent": fan.requested_percent,
        "fan_actual_percent": fan.actual_percent,
        "fan_backend_state": fan.backend.backend_state,
        "fan_mode": state.fan_mode,
        "display_status": display_status,
        "display_enabled_state": "ON" if state.display_enabled else "OFF",
        "hardware_fault": hardware_fault,
    }


if __name__ == "__main__":
    sys.exit(main())
