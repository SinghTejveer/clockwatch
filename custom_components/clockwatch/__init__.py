"""Clockwatch: receipts for every EV charge and drive, with solar share, cost per mile, and what petrol would have cost."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, DOMAIN, SERVICE_HISTORY
from .ledger import month_summary
from .tracker import Tracker

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ClockwatchConfigEntry = ConfigEntry[Tracker]

HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("kind", default="both"): vol.In(["charges", "trips", "both"]),
        vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional("month"): vol.Match(r"^\d{4}-\d{2}$"),
    }
)


def _entry(hass: HomeAssistant, call: ServiceCall) -> ClockwatchConfigEntry:
    loaded = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id := call.data.get("config_entry_id"):
        for e in loaded:
            if e.entry_id == entry_id:
                return e
        raise ServiceValidationError(f"No loaded Clockwatch entry with id {entry_id}")
    if len(loaded) == 1:
        return loaded[0]
    raise ServiceValidationError("Clockwatch is not set up" if not loaded else "More than one car is set up: say which with config_entry_id")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def history(call: ServiceCall) -> ServiceResponse:
        """Recent receipts, newest first, and the month's totals."""
        tracker = _entry(hass, call).runtime_data
        kind, limit, month = call.data["kind"], call.data["limit"], call.data.get("month")

        def pick(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [i for i in items if not month or str(i.get("ended", "")).startswith(month)]
            return list(reversed(items))[:limit]

        out: dict[str, Any] = {}
        if kind in ("charges", "both"):
            out["charges"] = pick(tracker.charges)
        if kind in ("trips", "both"):
            out["trips"] = pick(tracker.trips)
        out["month"] = month_summary(tracker.charges, tracker.trips, month) if month else tracker.month()
        return out

    hass.services.async_register(DOMAIN, SERVICE_HISTORY, history, schema=HISTORY_SCHEMA, supports_response=SupportsResponse.ONLY)
    await _register_cards(hass)
    return True


async def _register_cards(hass: HomeAssistant) -> None:
    """Serve the cards and load them on every dashboard, so they show in the card picker with no extra step. Skipped when there is no web
    server (tests, safe mode)."""
    if getattr(hass, "http", None) is None:
        return
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        path = Path(__file__).parent / "www" / "clockwatch-cards.js"
        await hass.async_add_executor_job(_remove_stale_compressed, path)
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), cache_headers=False)])
        version = (await hass.async_add_executor_job(_version)) or "0"
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    except Exception:
        _LOGGER.warning("Could not register the Clockwatch cards", exc_info=True)


def _remove_stale_compressed(path: Path) -> None:
    """A pre-compressed copy (.gz or .br) beside the cards is sent to browsers in their place; remove any older than the cards themselves."""
    for suffix in (".gz", ".br"):
        copy = path.with_name(path.name + suffix)
        try:
            if copy.exists() and copy.stat().st_mtime < path.stat().st_mtime:
                copy.unlink()
        except OSError as err:
            _LOGGER.warning("Could not remove %s: %s", copy, err)


def _version() -> str:
    import json

    return json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")).get("version", "0")


async def async_setup_entry(hass: HomeAssistant, entry: ClockwatchConfigEntry) -> bool:
    tracker = Tracker(hass, entry)
    await tracker.async_load()
    entry.runtime_data = tracker
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    tracker.async_start()
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClockwatchConfigEntry) -> bool:
    entry.runtime_data.async_stop()
    await entry.runtime_data.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _reload(hass: HomeAssistant, entry: ClockwatchConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
