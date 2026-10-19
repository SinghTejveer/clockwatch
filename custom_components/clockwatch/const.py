"""Constants for Clockwatch."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "clockwatch"

# car (Teslemetry)
CONF_CAR_DEVICE: Final = "car_device"
CONF_CHARGING_STATE: Final = "charging_state_entity"
CONF_CHARGER_POWER: Final = "charger_power_entity"
CONF_ENERGY_ADDED: Final = "energy_added_entity"
CONF_BATTERY_LEVEL: Final = "battery_level_entity"
CONF_ENERGY_REMAINING: Final = "energy_remaining_entity"
CONF_ODOMETER: Final = "odometer_entity"
CONF_SHIFT_STATE: Final = "shift_state_entity"
CONF_OUTSIDE_TEMP: Final = "outside_temp_entity"
CONF_SPEED: Final = "speed_entity"
CONF_LOCATION: Final = "location_entity"
CONF_CAPACITY: Final = "battery_capacity_kwh"

# home energy
CONF_SOLAR_POWER: Final = "solar_power_entity"
CONF_BATTERY_POWER: Final = "battery_power_entity"
CONF_GRID_POWER: Final = "grid_power_entity"
CONF_LOAD_POWER: Final = "load_power_entity"

# prices
CONF_IMPORT_PRICE_ENTITY: Final = "import_price_entity"
CONF_IMPORT_PRICE: Final = "import_price"
CONF_EXPORT_PRICE_ENTITY: Final = "export_price_entity"
CONF_EXPORT_PRICE: Final = "export_price"
CONF_SOLAR_VALUE: Final = "solar_value"
SOLAR_AT_EXPORT: Final = "export"
SOLAR_FREE: Final = "free"

# comparison car
CONF_COMPARE_NAME: Final = "compare_name"
CONF_COMPARE_ECONOMY: Final = "compare_economy"
CONF_COMPARE_UNIT: Final = "compare_economy_unit"
CONF_FUEL_PRICE: Final = "fuel_price_per_litre"
ECONOMY_MPG_UK: Final = "mpg_uk"
ECONOMY_MPG_US: Final = "mpg_us"
ECONOMY_L100KM: Final = "l_per_100km"

# trips
CONF_MIN_TRIP_MILES: Final = "min_trip_miles"
DEFAULT_MIN_TRIP_MILES: Final = 1.0
PARKED_MINUTES: Final = 5
PAUSE_MINUTES: Final = 60  # a charge "stopped" this long is over; shorter stops (a cheap-rate gap) are one charge
DEFAULT_MI_PER_KWH: Final = 3.5

DEFAULT_CAPACITY: Final = 57.5
DEFAULT_IMPORT_PRICE: Final = 0.25
DEFAULT_EXPORT_PRICE: Final = 0.15
DEFAULT_COMPARE_NAME: Final = "a petrol car"
DEFAULT_COMPARE_ECONOMY: Final = 40.0
DEFAULT_FUEL_PRICE: Final = 1.45

SAMPLE_SECONDS: Final = 60
MAX_HISTORY: Final = 500
STORAGE_VERSION: Final = 1

KM_PER_MILE: Final = 1.609344
LITRES_PER_UK_GALLON: Final = 4.54609
LITRES_PER_US_GALLON: Final = 3.785411784

EVENT_CHARGE: Final = "clockwatch_charge_finished"
EVENT_TRIP: Final = "clockwatch_trip_finished"
SERVICE_HISTORY: Final = "history"

SRC_SOLAR: Final = "solar"
SRC_BATTERY: Final = "battery"
SRC_GRID: Final = "grid"
SOURCES: Final = (SRC_SOLAR, SRC_BATTERY, SRC_GRID)

CARD_URL = "/clockwatch/clockwatch-cards.js"
