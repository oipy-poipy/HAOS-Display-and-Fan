from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
import ipaddress
import logging
import os
from pathlib import Path
import shutil
import socket
import time

import requests


LOGGER = logging.getLogger(__name__)
SUPERVISOR_BASE_URL = "http://supervisor"
HOST_INFO_CACHE_SECONDS = 300.0
HOST_INFO_RETRY_SECONDS = 30.0
# Addresses the add-on container itself lives on; never the address of the Pi on the LAN.
CONTAINER_NETWORKS = (
    ipaddress.ip_network("172.30.32.0/23"),  # Home Assistant Supervisor network
    ipaddress.ip_network("172.17.0.0/16"),  # Docker default bridge
)

_supervisor_cache: dict[str, tuple[float, str | None]] = {}


@dataclass
class SystemMetrics:
    hostname: str
    ip: str
    time: str
    clock: str
    date: str
    uptime: str
    uptime_short: str
    uptime_seconds: int
    cpu_temp_c: str
    cpu_load_1m: float
    mem_percent: int
    disk_percent: int

    def as_tokens(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def read_cpu_temp(path: str = "/sys/class/thermal/thermal_zone0/temp") -> str:
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
        return f"{int(raw) / 1000:.1f}"
    except (FileNotFoundError, PermissionError, ValueError):
        return "--"


def read_load_average() -> float:
    try:
        return float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    except (FileNotFoundError, IndexError, ValueError):
        return 0.0


def read_memory_percent() -> int:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        return round((total - available) / total * 100) if total else 0
    except (FileNotFoundError, ValueError, IndexError):
        return 0


def is_lan_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified:
        return False
    return not any(parsed in network for network in CONTAINER_NETWORKS)


def _interface_addresses(interface: dict) -> list[str]:
    ipv4 = interface.get("ipv4")
    if not isinstance(ipv4, dict):
        return []
    raw = ipv4.get("address", ipv4.get("ip_address", []))
    candidates = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    addresses = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        address = candidate.split("/", 1)[0].strip()
        if is_lan_address(address):
            addresses.append(address)
    return addresses


def parse_host_ip(payload: dict) -> str | None:
    """Pick the LAN address of the host from a Supervisor /network/info payload."""
    data = payload.get("data", payload)
    interfaces = data.get("interfaces") if isinstance(data, dict) else None
    if not isinstance(interfaces, list):
        return None
    ranked: list[tuple[int, str]] = []
    for interface in interfaces:
        if not isinstance(interface, dict) or interface.get("enabled") is False:
            continue
        rank = 0 if interface.get("primary") else 1 if interface.get("connected", True) else 2
        ranked.extend((rank, address) for address in _interface_addresses(interface))
    if not ranked:
        return None
    return min(ranked, key=lambda item: item[0])[1]


def _supervisor_data(path: str, timeout: int = 3) -> dict | None:
    """GET a Supervisor info endpoint. Role `default` is enough for /<area>/info paths."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        response = requests.get(SUPERVISOR_BASE_URL + path, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    except requests.RequestException as exc:
        LOGGER.debug("Supervisor request %s failed: %s", path, exc)
        return None
    if response.status_code != 200:
        LOGGER.debug("Supervisor %s returned %s", path, response.status_code)
        return None
    try:
        payload = response.json()
    except ValueError:
        LOGGER.debug("Supervisor %s returned invalid JSON", path)
        return None
    return payload if isinstance(payload, dict) else None


def fetch_host_ip() -> str | None:
    """The container address is never the address of the Pi on the LAN, so ask the Supervisor."""
    payload = _supervisor_data("/network/info")
    return parse_host_ip(payload) if payload else None


def fetch_host_name() -> str | None:
    payload = _supervisor_data("/host/info")
    data = payload.get("data", payload) if payload else None
    name = data.get("hostname") if isinstance(data, dict) else None
    return str(name) if isinstance(name, str) and name.strip() else None


def _cached(key: str, loader, now: float | None = None) -> str | None:
    now = time.monotonic() if now is None else now
    cached = _supervisor_cache.get(key)
    if cached is not None:
        cached_at, value = cached
        ttl = HOST_INFO_CACHE_SECONDS if value else HOST_INFO_RETRY_SECONDS
        if now - cached_at < ttl:
            return value
    value = loader()
    _supervisor_cache[key] = (now, value)
    return value


def host_ip(now: float | None = None) -> str | None:
    return _cached("ip", fetch_host_ip, now)


def host_name(now: float | None = None) -> str | None:
    return _cached("hostname", fetch_host_name, now)


def read_local_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    return address if is_lan_address(address) else None


def read_primary_ip() -> str:
    return host_ip() or read_local_ip() or "--"


def read_hostname() -> str:
    return host_name() or socket.gethostname()


def read_uptime() -> tuple[str, int]:
    try:
        seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (FileNotFoundError, ValueError, IndexError):
        seconds = int(time.monotonic())
    return str(timedelta(seconds=seconds)).split(".", 1)[0], seconds


def format_uptime_short(seconds: int) -> str:
    """Compact uptime that fits a 128 pixel row, for example 3d 4h."""
    minutes, hours = seconds // 60 % 60, seconds // 3600
    if hours >= 24:
        return f"{hours // 24}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def collect_metrics() -> SystemMetrics:
    now = time.localtime()
    uptime_text, uptime_seconds = read_uptime()
    disk = shutil.disk_usage("/")
    return SystemMetrics(
        hostname=read_hostname(),
        ip=read_primary_ip(),
        time=time.strftime("%H:%M:%S", now),
        clock=time.strftime("%H:%M", now),
        date=time.strftime("%Y-%m-%d", now),
        uptime=uptime_text,
        uptime_short=format_uptime_short(uptime_seconds),
        uptime_seconds=uptime_seconds,
        cpu_temp_c=read_cpu_temp(),
        cpu_load_1m=read_load_average(),
        mem_percent=read_memory_percent(),
        disk_percent=round(disk.used / disk.total * 100) if disk.total else 0,
    )


def architecture() -> str:
    return os.uname().machine if hasattr(os, "uname") else "unknown"
