"""A Home Assistant with a Teslemetry car and energy site in its registries, Octopus price sensors, and helpers to drive time by hand."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.clockwatch.const import DOMAIN

VIN = "LRW3TESTVIN000001"
SITE = "1689599282354470"
IMPORT = "sensor.octopus_energy_electricity_aa_bb_current_rate"
EXPORT = "sensor.octopus_energy_electricity_aa_cc_export_current_rate"

CAR_SENSORS = {  # unique-id suffix: (object id, state, unit)
    "charge_state_charging_state": ("charging", "disconnected", None),
    "charge_state_charger_power": ("charger_power", "0", "kW"),
    "charge_state_charge_energy_added": ("charge_energy_added", "0", "kWh"),
    "charge_state_battery_level": ("battery_level", "41", "%"),
    "energy_remaining": ("energy_remaining", "23.6", "kWh"),
    "vehicle_state_odometer": ("odometer", "1000.0", "mi"),
    "drive_state_shift_state": ("shift_state", "p", None),
    "drive_state_speed": ("speed", "0", "mph"),
    "climate_state_outside_temp": ("outside_temperature", "9", "°C"),
}
SITE_SENSORS = {"solar_power": "my_home_solar_power", "battery_power": "my_home_battery_power", "grid_power": "my_home_grid_power",
                "load_power": "my_home_load_power"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def put(hass: HomeAssistant, entity_id: str, state: Any, unit: str | None = None) -> None:
    hass.states.async_set(entity_id, str(state), {"unit_of_measurement": unit} if unit else {})


@pytest.fixture
async def car(hass: HomeAssistant) -> str:
    """The Teslemetry car and energy site, with every sensor reporting. -> the car's device id."""
    hass.config.currency = "GBP"
    tes = MockConfigEntry(domain="teslemetry", title="Teslemetry", data={})
    tes.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    car_dev = dev_reg.async_get_or_create(config_entry_id=tes.entry_id, identifiers={("teslemetry", VIN)}, name="Model 3")
    site = dev_reg.async_get_or_create(config_entry_id=tes.entry_id, identifiers={("teslemetry", SITE)}, name="My Home")
    for suffix, (obj, state, unit) in CAR_SENSORS.items():
        e = ent_reg.async_get_or_create("sensor", "teslemetry", f"{VIN}-{suffix}", device_id=car_dev.id, config_entry=tes, suggested_object_id=obj)
        put(hass, e.entity_id, state, unit)
    for suffix, obj in SITE_SENSORS.items():
        e = ent_reg.async_get_or_create("sensor", "teslemetry", f"{SITE}-{suffix}", device_id=site.id, config_entry=tes, suggested_object_id=obj)
        put(hass, e.entity_id, "0", "kW")
    put(hass, IMPORT, "0.075", "GBP/kWh")
    put(hass, EXPORT, "0.09", "GBP/kWh")
    return car_dev.id


def settings(car_id: str, **over: Any) -> dict[str, Any]:
    return {
        "car_device": car_id,
        "charging_state_entity": "sensor.charging",
        "charger_power_entity": "sensor.charger_power",
        "energy_added_entity": "sensor.charge_energy_added",
        "battery_level_entity": "sensor.battery_level",
        "energy_remaining_entity": "sensor.energy_remaining",
        "odometer_entity": "sensor.odometer",
        "shift_state_entity": "sensor.shift_state",
        "speed_entity": "sensor.speed",
        "outside_temp_entity": "sensor.outside_temperature",
        "battery_capacity_kwh": 57.5,
        "solar_power_entity": "sensor.my_home_solar_power",
        "battery_power_entity": "sensor.my_home_battery_power",
        "grid_power_entity": "sensor.my_home_grid_power",
        "load_power_entity": "sensor.my_home_load_power",
        "import_price_entity": IMPORT,
        "import_price": 0.25,
        "export_price_entity": EXPORT,
        "export_price": 0.15,
        "solar_value": "export",
        "compare_name": "the X3 M40i",
        "compare_economy": 30.0,
        "compare_economy_unit": "mpg_uk",
        "fuel_price_per_litre": 1.90,
        "min_trip_miles": 1.0,
        **over,
    }


@pytest.fixture
async def setup_entry(hass: HomeAssistant, car: str):
    async def _setup(**over: Any) -> MockConfigEntry:
        entry = MockConfigEntry(domain=DOMAIN, title="Clockwatch · Model 3", unique_id=car, data=settings(car, **over))
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


class Clock:
    """Drive the tracker by hand: set sensors, then step a minute at a time."""

    def __init__(self, hass: HomeAssistant, entry: MockConfigEntry, start: datetime | None = None) -> None:
        self.hass, self.t = hass, entry.runtime_data
        self.now = start or datetime(2026, 10, 19, 13, 0, tzinfo=dt_util.get_default_time_zone())

    def house(self, solar: float, battery: float, grid: float, load: float) -> None:
        for name, v in (("solar", solar), ("battery", battery), ("grid", grid), ("load", load)):
            put(self.hass, f"sensor.my_home_{name}_power", v, "kW")

    def set(self, entity_id: str, value: Any, unit: str | None = None) -> None:
        put(self.hass, entity_id, value, unit or (self.hass.states.get(entity_id).attributes.get("unit_of_measurement") if self.hass.states.get(entity_id) else None))

    def step(self, minutes: int = 1) -> None:
        for _ in range(minutes):
            self.now += timedelta(minutes=1)
            self.t.sample(self.now)
            self.t.check(self.now)
