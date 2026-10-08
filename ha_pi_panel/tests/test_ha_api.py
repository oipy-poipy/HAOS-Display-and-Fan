import app.ha_api as ha_api_module
from app.ha_api import HomeAssistantApi, split_entity_ref


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no payload")
        return self._payload


def build_api(monkeypatch, responses, calls=None):
    def fake_get(url, headers=None, timeout=None):
        entity_id = url.rsplit("/", 1)[1]
        if calls is not None:
            calls.append(entity_id)
        return responses.get(entity_id, FakeResponse(404))

    monkeypatch.setattr(ha_api_module.requests, "get", fake_get)
    return HomeAssistantApi(token="token")


def test_split_entity_ref():
    assert split_entity_ref("weather.home@temperature") == ("weather.home", "temperature")
    assert split_entity_ref(" sensor.one ") == ("sensor.one", None)


def test_get_state_reads_state_and_attribute(monkeypatch):
    responses = {"weather.home": FakeResponse(200, {"state": "partlycloudy", "attributes": {"temperature": 12.3}})}
    api = build_api(monkeypatch, responses)

    assert api.get_state("weather.home") == "partlycloudy"
    assert api.get_state("weather.home@temperature") == "12.3"


def test_get_state_returns_missing_for_unknown_entity_and_attribute(monkeypatch):
    responses = {"sensor.one": FakeResponse(200, {"state": "unavailable", "attributes": {}})}
    api = build_api(monkeypatch, responses)

    assert api.get_state("sensor.one") == "--"
    assert api.get_state("sensor.one@humidity") == "--"
    assert api.get_state("sensor.gone") == "--"


def test_get_state_without_token_is_missing(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    api = HomeAssistantApi(token=None)

    assert api.available is False
    assert api.get_state("sensor.one") == "--"


def test_one_request_serves_several_refs_of_the_same_entity(monkeypatch):
    calls: list[str] = []
    responses = {"weather.home": FakeResponse(200, {"state": "sunny", "attributes": {"temperature": 20, "humidity": 55}})}
    api = build_api(monkeypatch, responses, calls)

    api.warm_cache(["weather.home@temperature", "weather.home@humidity"])
    api.get_state("weather.home@temperature")
    api.get_state("weather.home@humidity")

    assert calls == ["weather.home"]


def test_missing_entity_is_reported_once(monkeypatch, caplog):
    api = build_api(monkeypatch, {})

    with caplog.at_level("WARNING"):
        api.get_state("sensor.gone")
        api._cache.clear()
        api.get_state("sensor.gone")

    warnings = [record for record in caplog.records if record.levelname == "WARNING" and "sensor.gone" in record.getMessage()]
    assert len(warnings) == 1
