from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterable

import requests


LOGGER = logging.getLogger(__name__)
MISSING = "--"
UNUSABLE_STATES = {"unknown", "unavailable", "none", ""}


def split_entity_ref(ref: str) -> tuple[str, str | None]:
    """Split ``weather.home@temperature`` into entity id and attribute name."""
    entity_id, _, attribute = ref.partition("@")
    attribute = attribute.strip()
    return entity_id.strip(), attribute or None


class HomeAssistantApi:
    def __init__(self, token: str | None = None, base_url: str = "http://supervisor/core/api/", timeout: int = 5, cache_seconds: float = 5.0) -> None:
        self.token = token or os.environ.get("SUPERVISOR_TOKEN")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._reported: set[str] = set()

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _report_once(self, entity_id: str, message: str, *args: Any) -> None:
        if entity_id in self._reported:
            LOGGER.debug(message, *args)
            return
        self._reported.add(entity_id)
        LOGGER.warning(message, *args)

    def _fetch(self, entity_id: str) -> dict[str, Any] | None:
        cached = self._cache.get(entity_id)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        payload: dict[str, Any] | None = None
        try:
            response = requests.get(
                self.base_url + "states/" + entity_id,
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            self._report_once(entity_id, "Home Assistant API request failed for %s: %s", entity_id, exc)
        else:
            if response.status_code == 404:
                self._report_once(entity_id, "Home Assistant has no entity %s; check the id in Developer Tools, States.", entity_id)
            elif response.status_code == 401:
                self._report_once(entity_id, "Home Assistant API rejected the add-on token (401). Is homeassistant_api enabled?")
            elif response.status_code != 200:
                self._report_once(entity_id, "Home Assistant API returned %s for %s", response.status_code, entity_id)
            else:
                try:
                    decoded = response.json()
                except ValueError:
                    self._report_once(entity_id, "Home Assistant API returned invalid JSON for %s", entity_id)
                else:
                    payload = decoded if isinstance(decoded, dict) else None
        self._cache[entity_id] = (time.monotonic(), payload)
        return payload

    def get_state(self, ref: str) -> str:
        """Return the state, or an attribute value when the ref uses ``entity@attribute``."""
        if not self.token:
            return MISSING
        entity_id, attribute = split_entity_ref(ref)
        if not entity_id:
            return MISSING
        payload = self._fetch(entity_id)
        if payload is None:
            return MISSING
        if attribute:
            attributes = payload.get("attributes")
            raw = attributes.get(attribute) if isinstance(attributes, dict) else None
            if raw is None:
                self._report_once(f"{entity_id}@{attribute}", "Entity %s has no attribute %s", entity_id, attribute)
        else:
            raw = payload.get("state")
        value = MISSING if raw is None else str(raw).strip()
        return MISSING if value.lower() in UNUSABLE_STATES else value

    def warm_cache(self, refs: Iterable[str]) -> None:
        for entity_id in {split_entity_ref(ref)[0] for ref in refs}:
            if entity_id and self.token:
                self._fetch(entity_id)
