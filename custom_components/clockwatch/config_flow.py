"""Setup in four short steps: the car, the home's energy, the prices, and the petrol car to compare with. Everything is found automatically where
it can be, and can be changed later (Configure)."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_BATTERY_LEVEL,
    CONF_BATTERY_POWER,
    CONF_CAPACITY,
    CONF_CAR_DEVICE,
    CONF_CHARGER_POWER,
    CONF_CHARGING_STATE,
    CONF_COMPARE_ECONOMY,
    CONF_COMPARE_NAME,
    CONF_COMPARE_UNIT,
    CONF_ENERGY_ADDED,
    CONF_ENERGY_REMAINING,
    CONF_EXPORT_PRICE,
    CONF_EXPORT_PRICE_ENTITY,
    CONF_FUEL_PRICE,
    CONF_GRID_POWER,
    CONF_IMPORT_PRICE,
    CONF_IMPORT_PRICE_ENTITY,
    CONF_LOAD_POWER,
    CONF_MIN_TRIP_MILES,
    CONF_ODOMETER,
    CONF_OUTSIDE_TEMP,
    CONF_SHIFT_STATE,
    CONF_SOLAR_POWER,
    CONF_SOLAR_VALUE,
    CONF_SPEED,
    DEFAULT_CAPACITY,
    DEFAULT_COMPARE_ECONOMY,
    DEFAULT_COMPARE_NAME,
    DEFAULT_EXPORT_PRICE,
    DEFAULT_FUEL_PRICE,
    DEFAULT_IMPORT_PRICE,
    DEFAULT_MIN_TRIP_MILES,
    DOMAIN,
    ECONOMY_L100KM,
    ECONOMY_MPG_UK,
    ECONOMY_MPG_US,
    SOLAR_AT_EXPORT,
    SOLAR_FREE,
)

TESLEMETRY = "teslemetry"
# the Teslemetry sensor each setting comes from, by the end of its unique id (several names: polling and streaming differ)
CAR_KEYS: dict[str, tuple[str, ...]] = {
    CONF_CHARGING_STATE: ("charge_state_charging_state",),
    CONF_CHARGER_POWER: ("charge_state_charger_power",),
    CONF_ENERGY_ADDED: ("charge_state_charge_energy_added",),
    CONF_BATTERY_LEVEL: ("charge_state_battery_level", "charge_state_usable_battery_level"),
    CONF_ENERGY_REMAINING: ("energy_remaining",),
    CONF_ODOMETER: ("vehicle_state_odometer",),
    CONF_SHIFT_STATE: ("drive_state_shift_state",),
    CONF_SPEED: ("drive_state_speed",),
    CONF_OUTSIDE_TEMP: ("climate_state_outside_temp",),
}
REQUIRED_CAR = (CONF_CHARGING_STATE, CONF_CHARGER_POWER, CONF_ODOMETER, CONF_SHIFT_STATE)
SITE_KEYS = {CONF_SOLAR_POWER: "solar_power", CONF_BATTERY_POWER: "battery_power", CONF_GRID_POWER: "grid_power", CONF_LOAD_POWER: "load_power"}
SENSOR = EntitySelector(EntitySelectorConfig(domain="sensor"))


def find_cars(hass: HomeAssistant) -> dict[str, str]:
    """Teslemetry cars (devices with a charging-state sensor) -> {device id: name}."""
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    cars: dict[str, str] = {}
    for entry in hass.config_entries.async_entries(TESLEMETRY):
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            if any((e.unique_id or "").endswith("-charge_state_charging_state") for e in er.async_entries_for_device(ent_reg, device.id, True)):
                cars[device.id] = device.name_by_user or device.name or "Car"
    return cars


def detect(hass: HomeAssistant, device_id: str) -> tuple[dict[str, Any], list[str]]:
    """The car's sensors, the home's energy sensors and the price sensors that can be found -> (settings, car sensors that are switched off)."""
    ent_reg = er.async_get(hass)
    device = dr.async_get(hass).async_get(device_id)
    found: dict[str, Any] = {}
    disabled: list[str] = []
    car_entities = er.async_entries_for_device(ent_reg, device_id, True)
    for key, suffixes in CAR_KEYS.items():
        for suffix in suffixes:
            e = next((e for e in car_entities if e.platform == TESLEMETRY and (e.unique_id or "").endswith("-" + suffix)), None)
            if e:
                found[key] = e.entity_id
                if e.disabled_by and key in REQUIRED_CAR + (CONF_BATTERY_LEVEL,):
                    disabled.append(e.entity_id)
                break
    if device:  # the energy site in the same Teslemetry account
        for entry_id in device.config_entries:
            for e in er.async_entries_for_config_entry(ent_reg, entry_id):
                for key, suffix in SITE_KEYS.items():
                    if e.platform == TESLEMETRY and e.domain == "sensor" and (e.unique_id or "").endswith("-" + suffix) and not e.disabled_by:
                        found.setdefault(key, e.entity_id)
    for st in hass.states.async_all("sensor"):
        if re.search(r"electricity_.*_export_current_rate$", st.entity_id):
            found.setdefault(CONF_EXPORT_PRICE_ENTITY, st.entity_id)
        elif re.search(r"electricity_.*_current_rate$", st.entity_id):
            found.setdefault(CONF_IMPORT_PRICE_ENTITY, st.entity_id)
    return found, disabled


def _opt(key: str, d: dict[str, Any]) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": d.get(key)})


def car_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            **{_opt(k, d): SENSOR for k in CAR_KEYS},
            vol.Required(CONF_CAPACITY, default=d.get(CONF_CAPACITY, DEFAULT_CAPACITY)): NumberSelector(
                NumberSelectorConfig(min=10, max=250, step=0.5, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
            ),
        }
    )


def home_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema({_opt(k, d): SENSOR for k in SITE_KEYS})


def price_schema(d: dict[str, Any], currency: str) -> vol.Schema:
    money = NumberSelectorConfig(min=0, max=5, step="any", unit_of_measurement=f"{currency}/kWh", mode=NumberSelectorMode.BOX)
    return vol.Schema(
        {
            _opt(CONF_IMPORT_PRICE_ENTITY, d): SENSOR,
            vol.Required(CONF_IMPORT_PRICE, default=d.get(CONF_IMPORT_PRICE, DEFAULT_IMPORT_PRICE)): NumberSelector(money),
            _opt(CONF_EXPORT_PRICE_ENTITY, d): SENSOR,
            vol.Required(CONF_EXPORT_PRICE, default=d.get(CONF_EXPORT_PRICE, DEFAULT_EXPORT_PRICE)): NumberSelector(money),
            vol.Required(CONF_SOLAR_VALUE, default=d.get(CONF_SOLAR_VALUE, SOLAR_AT_EXPORT)): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=SOLAR_AT_EXPORT, label="The export price I give up"), SelectOptionDict(value=SOLAR_FREE, label="Free")],
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
    )


def compare_schema(d: dict[str, Any], currency: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_COMPARE_NAME, default=d.get(CONF_COMPARE_NAME, DEFAULT_COMPARE_NAME)): TextSelector(),
            vol.Required(CONF_COMPARE_ECONOMY, default=d.get(CONF_COMPARE_ECONOMY, DEFAULT_COMPARE_ECONOMY)): NumberSelector(
                NumberSelectorConfig(min=1, max=200, step=0.1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_COMPARE_UNIT, default=d.get(CONF_COMPARE_UNIT, ECONOMY_MPG_UK)): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=ECONOMY_MPG_UK, label="mpg (UK)"),
                        SelectOptionDict(value=ECONOMY_MPG_US, label="mpg (US)"),
                        SelectOptionDict(value=ECONOMY_L100KM, label="litres per 100 km"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_FUEL_PRICE, default=d.get(CONF_FUEL_PRICE, DEFAULT_FUEL_PRICE)): NumberSelector(
                NumberSelectorConfig(min=0, max=10, step=0.001, unit_of_measurement=f"{currency}/litre", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MIN_TRIP_MILES, default=d.get(CONF_MIN_TRIP_MILES, DEFAULT_MIN_TRIP_MILES)): NumberSelector(
                NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="mi", mode=NumberSelectorMode.BOX)
            ),
        }
    )


def check_car(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Errors for the car step: the four sensors a receipt needs must be chosen and reporting."""
    errors: dict[str, str] = {}
    for key in REQUIRED_CAR:
        eid = data.get(key)
        if not eid:
            errors[key] = "required"
        elif hass.states.get(eid) is None:
            errors[key] = "not_reporting"
    return errors


class ClockwatchConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._found: dict[str, Any] = {}
        self._disabled: list[str] = []

    @property
    def _currency(self) -> str:
        return self.hass.config.currency or "GBP"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        cars = find_cars(self.hass)
        if not cars:
            return self.async_abort(reason="no_cars")
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CAR_DEVICE])
            self._abort_if_unique_id_configured()
            self._data[CONF_CAR_DEVICE] = user_input[CONF_CAR_DEVICE]
            self._found, self._disabled = detect(self.hass, user_input[CONF_CAR_DEVICE])
            return await self.async_step_car()
        options = [SelectOptionDict(value=k, label=f"{v} (Teslemetry)") for k, v in cars.items()]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_CAR_DEVICE, default=options[0]["value"]): SelectSelector(SelectSelectorConfig(options=options))}),
        )

    async def async_step_car(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = check_car(self.hass, user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_home()
        shown = user_input or {**self._found}
        placeholders = {"disabled": ", ".join(self._disabled) if self._disabled else "none"}
        return self.async_show_form(step_id="car", data_schema=car_schema(shown), errors=errors, description_placeholders=placeholders)

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_prices()
        return self.async_show_form(step_id="home", data_schema=home_schema(self._found))

    async def async_step_prices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_compare()
        return self.async_show_form(step_id="prices", data_schema=price_schema(self._found, self._currency))

    async def async_step_compare(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            name = find_cars(self.hass).get(self._data[CONF_CAR_DEVICE], "car")
            return self.async_create_entry(title=f"Clockwatch · {name}", data=self._data)
        return self.async_show_form(step_id="compare", data_schema=compare_schema({}, self._currency))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ClockwatchOptionsFlow()


class ClockwatchOptionsFlow(OptionsFlow):
    """Change any setting later: the same steps, filled in."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options, **self._options}

    @property
    def _currency(self) -> str:
        return self.hass.config.currency or "GBP"

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = check_car(self.hass, user_input)
            if not errors:
                self._options.update(user_input)
                return await self.async_step_home()
        return self.async_show_form(
            step_id="init", data_schema=car_schema(user_input or self._current), errors=errors, description_placeholders={"disabled": "none"}
        )

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update({k: user_input.get(k) for k in SITE_KEYS})
            return await self.async_step_prices()
        return self.async_show_form(step_id="home", data_schema=home_schema(self._current))

    async def async_step_prices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update({CONF_IMPORT_PRICE_ENTITY: None, CONF_EXPORT_PRICE_ENTITY: None, **user_input})
            return await self.async_step_compare()
        return self.async_show_form(step_id="prices", data_schema=price_schema(self._current, self._currency))

    async def async_step_compare(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)
        return self.async_show_form(step_id="compare", data_schema=compare_schema(self._current, self._currency))
