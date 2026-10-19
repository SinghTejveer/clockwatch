"""Sensors: the last charge, the last trip, and this month's totals. The cards read the receipts from their attributes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClockwatchConfigEntry
from .const import DOMAIN
from .tracker import Tracker, signal


@dataclass(frozen=True, kw_only=True)
class ClockwatchSensorDescription(SensorEntityDescription):
    value: Callable[[Tracker], Any]
    attrs: Callable[[Tracker], dict[str, Any]] | None = None
    money: bool = False


def _pct(v: float | None) -> float | None:
    return round(v * 100, 1) if v is not None else None


def _receipt(r: dict[str, Any] | None) -> dict[str, Any]:
    return dict(r or {})


DESCRIPTIONS: tuple[ClockwatchSensorDescription, ...] = (
    ClockwatchSensorDescription(
        key="last_charge",
        translation_key="last_charge",
        icon="mdi:ev-station",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        value=lambda t: (t.last_charge or {}).get("kwh"),
        attrs=lambda t: _receipt(t.last_charge),
    ),
    ClockwatchSensorDescription(
        key="last_trip",
        translation_key="last_trip",
        icon="mdi:receipt-text-outline",
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        value=lambda t: (t.last_trip or {}).get("miles"),
        attrs=lambda t: _receipt(t.last_trip),
    ),
    ClockwatchSensorDescription(
        key="month_charge_cost",
        translation_key="month_charge_cost",
        icon="mdi:cash",
        money=True,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value=lambda t: t.month()["charge_cost"],
        attrs=lambda t: t.month(),
    ),
    ClockwatchSensorDescription(
        key="month_solar_share",
        translation_key="month_solar_share",
        icon="mdi:white-balance-sunny",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda t: _pct(t.month()["solar_share"]),
    ),
    ClockwatchSensorDescription(
        key="month_miles",
        translation_key="month_miles",
        icon="mdi:road-variant",
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        value=lambda t: t.month()["miles"],
    ),
    ClockwatchSensorDescription(
        key="month_cost_per_mile",
        translation_key="month_cost_per_mile",
        icon="mdi:cash-marker",
        money=True,
        value=lambda t: round(t.month()["cost_per_mile"] * 100, 2) if t.month()["cost_per_mile"] is not None else None,
    ),
    ClockwatchSensorDescription(
        key="month_saved",
        translation_key="month_saved",
        icon="mdi:gas-station-off-outline",
        money=True,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value=lambda t: t.month()["saved"],
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ClockwatchConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(ClockwatchSensor(entry, d) for d in DESCRIPTIONS)


class ClockwatchSensor(SensorEntity):
    entity_description: ClockwatchSensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False
    _unrecorded_attributes = frozenset({"curve", "energy", "cost_by_source"})

    def __init__(self, entry: ClockwatchConfigEntry, description: ClockwatchSensorDescription) -> None:
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer="Clockwatch", entry_type=DeviceEntryType.SERVICE
        )

    async def async_added_to_hass(self) -> None:
        if self.entity_description.money:
            currency = self.hass.config.currency or "GBP"
            self._attr_native_unit_of_measurement = (
                "p/mi"
                if self.entity_description.key == "month_cost_per_mile" and currency == "GBP"
                else (f"{currency}/100 mi" if self.entity_description.key == "month_cost_per_mile" else currency)
            )
        self.async_on_remove(async_dispatcher_connect(self.hass, signal(self._entry.entry_id), self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self._entry.runtime_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs(self._entry.runtime_data) if self.entity_description.attrs else None
