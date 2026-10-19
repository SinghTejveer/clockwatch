"""Diagnostics: the settings, the stored-energy records and the last receipts. No locations are kept, so nothing needs hiding."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import ClockwatchConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ClockwatchConfigEntry) -> dict[str, Any]:
    t = entry.runtime_data
    return {
        "settings": {**entry.data, **entry.options},
        "car_store": t.car.to_dict(),
        "home_store": t.home.to_dict(),
        "charge_in_progress": t.charge.to_dict() if t.charge else None,
        "trip_in_progress": t.trip.to_dict() if t.trip else None,
        "charges": len(t.charges),
        "trips": len(t.trips),
        "last_charge": {k: v for k, v in (t.last_charge or {}).items() if k != "curve"},
        "last_trip": t.last_trip,
    }
