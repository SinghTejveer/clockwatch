"""Setup: the car's, the home's and the price sensors are found by themselves; the required ones are checked; Configure changes them later."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.clockwatch.const import DOMAIN

from .conftest import EXPORT, IMPORT, VIN

COMPARE = {"compare_name": "the X3 M40i", "compare_economy": 30, "compare_economy_unit": "mpg_uk", "fuel_price_per_litre": 1.9, "min_trip_miles": 1}


def suggested(result, key):
    for k in result["data_schema"].schema:
        if str(k) == key:
            return (k.description or {}).get("suggested_value")
    return None


async def test_everything_is_found_and_the_entry_created(hass: HomeAssistant, car: str) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"car_device": car})
    assert r["step_id"] == "car"
    assert suggested(r, "charging_state_entity") == "sensor.charging" and suggested(r, "odometer_entity") == "sensor.odometer"
    assert suggested(r, "energy_remaining_entity") == "sensor.energy_remaining"
    car_data = {k: suggested(r, k) for k in ("charging_state_entity", "charger_power_entity", "energy_added_entity", "battery_level_entity",
                                             "energy_remaining_entity", "odometer_entity", "shift_state_entity", "speed_entity", "outside_temp_entity")}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**car_data, "battery_capacity_kwh": 57.5})
    assert r["step_id"] == "home"
    assert suggested(r, "solar_power_entity") == "sensor.my_home_solar_power" and suggested(r, "load_power_entity") == "sensor.my_home_load_power"
    home = {k: suggested(r, k) for k in ("solar_power_entity", "battery_power_entity", "grid_power_entity", "load_power_entity")}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], home)
    assert r["step_id"] == "prices"
    assert suggested(r, "import_price_entity") == IMPORT and suggested(r, "export_price_entity") == EXPORT
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"import_price_entity": IMPORT, "import_price": 0.25, "export_price_entity": EXPORT,
                                                                      "export_price": 0.15, "solar_value": "export"})
    assert r["step_id"] == "compare"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], COMPARE)
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["title"] == "Clockwatch · Model 3"
    assert r["data"]["shift_state_entity"] == "sensor.shift_state" and r["data"]["export_price_entity"] == EXPORT and r["data"]["compare_economy"] == 30


async def test_required_sensors_are_checked(hass: HomeAssistant, car: str) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"car_device": car})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"charging_state_entity": "sensor.charging", "charger_power_entity": "sensor.charger_power",
                                                                      "odometer_entity": "sensor.not_there", "battery_capacity_kwh": 57.5})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "car"
    assert r["errors"] == {"odometer_entity": "not_reporting", "shift_state_entity": "required"}


async def test_switched_off_teslemetry_sensors_are_named(hass: HomeAssistant, car: str) -> None:
    ent_reg = er.async_get(hass)
    e = ent_reg.async_get_entity_id("sensor", "teslemetry", f"{VIN}-drive_state_shift_state")
    ent_reg.async_update_entity(e, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"car_device": car})
    assert "sensor.shift_state" in r["description_placeholders"]["disabled"]


async def test_no_teslemetry_car_stops_with_a_reason(hass: HomeAssistant) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "no_cars"


async def test_the_same_car_twice_is_refused(hass: HomeAssistant, setup_entry, car: str) -> None:
    await setup_entry()
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"car_device": car})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "already_configured"


async def test_configure_changes_the_comparison_car_and_drops_a_price_sensor(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["step_id"] == "init"
    car_keys = ("charging_state_entity", "charger_power_entity", "odometer_entity", "shift_state_entity")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**{k: entry.data[k] for k in car_keys}, "battery_capacity_kwh": 75})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"import_price": 0.28, "export_price": 0.15, "solar_value": "free"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMPARE, "compare_name": "a Golf", "compare_economy": 45})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    t = entry.runtime_data
    assert t.capacity == 75 and t.conf["compare_name"] == "a Golf" and t.import_price() == 0.28 and t.solar_value() == 0.0
    assert t.conf["solar_power_entity"] is None, "an empty home step clears the home sensors"
