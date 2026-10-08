from app import system_metrics


NETWORK_INFO = {
    "result": "ok",
    "data": {
        "interfaces": [
            {"interface": "hassio", "primary": False, "connected": True, "ipv4": {"address": ["172.30.32.1/23"]}},
            {"interface": "wlan0", "primary": False, "connected": False, "enabled": False, "ipv4": {"address": ["192.168.1.99/24"]}},
            {"interface": "eth0", "primary": True, "connected": True, "ipv4": {"address": ["192.168.1.50/24"]}},
        ]
    },
}


def test_parse_host_ip_prefers_the_primary_lan_interface():
    assert system_metrics.parse_host_ip(NETWORK_INFO) == "192.168.1.50"


def test_parse_host_ip_ignores_container_networks():
    payload = {"data": {"interfaces": [{"interface": "hassio", "connected": True, "ipv4": {"address": ["172.30.32.1/23"]}}]}}

    assert system_metrics.parse_host_ip(payload) is None


def test_parse_host_ip_accepts_single_string_address():
    payload = {"data": {"interfaces": [{"interface": "eth0", "primary": True, "ipv4": {"ip_address": "10.0.0.8/24"}}]}}

    assert system_metrics.parse_host_ip(payload) == "10.0.0.8"


def test_parse_host_ip_tolerates_junk():
    assert system_metrics.parse_host_ip({}) is None
    assert system_metrics.parse_host_ip({"data": {"interfaces": [None, {"ipv4": None}]}}) is None


def test_is_lan_address_rejects_loopback_and_container_ranges():
    assert system_metrics.is_lan_address("192.168.1.50")
    assert not system_metrics.is_lan_address("127.0.0.1")
    assert not system_metrics.is_lan_address("172.17.0.4")
    assert not system_metrics.is_lan_address("nonsense")


def test_read_primary_ip_falls_back_to_the_local_socket(monkeypatch):
    system_metrics._supervisor_cache.clear()
    monkeypatch.setattr(system_metrics, "fetch_host_ip", lambda: None)
    monkeypatch.setattr(system_metrics, "read_local_ip", lambda: "192.168.1.77")

    assert system_metrics.read_primary_ip() == "192.168.1.77"


def test_read_primary_ip_reports_missing_instead_of_the_container_address(monkeypatch):
    system_metrics._supervisor_cache.clear()
    monkeypatch.setattr(system_metrics, "fetch_host_ip", lambda: None)
    monkeypatch.setattr(system_metrics, "read_local_ip", lambda: None)

    assert system_metrics.read_primary_ip() == "--"


def test_host_ip_is_cached_and_retried_after_the_backoff(monkeypatch):
    system_metrics._supervisor_cache.clear()
    calls: list[int] = []

    def fake_fetch():
        calls.append(1)
        return "192.168.1.50" if len(calls) > 1 else None

    monkeypatch.setattr(system_metrics, "fetch_host_ip", fake_fetch)

    assert system_metrics.host_ip(now=0.0) is None
    assert system_metrics.host_ip(now=10.0) is None
    assert system_metrics.host_ip(now=system_metrics.HOST_INFO_RETRY_SECONDS + 1) == "192.168.1.50"
    assert system_metrics.host_ip(now=system_metrics.HOST_INFO_RETRY_SECONDS + 2) == "192.168.1.50"
    assert len(calls) == 2


def test_format_uptime_short():
    assert system_metrics.format_uptime_short(90) == "1m"
    assert system_metrics.format_uptime_short(3 * 3600 + 25 * 60) == "3h 25m"
    assert system_metrics.format_uptime_short(3 * 86400 + 4 * 3600) == "3d 4h"


def test_collect_metrics_exposes_display_tokens(monkeypatch):
    system_metrics._supervisor_cache.clear()
    monkeypatch.setattr(system_metrics, "fetch_host_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(system_metrics, "fetch_host_name", lambda: "homeassistant")

    tokens = system_metrics.collect_metrics().as_tokens()

    assert tokens["ip"] == "192.168.1.50"
    assert tokens["hostname"] == "homeassistant"
    assert len(tokens["clock"]) == 5
