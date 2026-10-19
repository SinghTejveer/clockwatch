"""Charges and trips played a minute at a time against a fake car and house; the receipts, the sensors, the action and the events."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.clockwatch.const import DOMAIN, EVENT_CHARGE, EVENT_TRIP

from .conftest import EXPORT, IMPORT, Clock

approx = pytest.approx


def start(clock: Clock) -> None:
    clock.t.sample(clock.now)  # the first sample only sets the clock
    clock.t.check(clock.now)


def sunny_charge(clock: Clock, *, cloud: bool = True) -> None:
    """Car charging at 7 kW for 60 minutes in the sun; 20 minutes of cloud covered by the Powerwall."""
    clock.set("sensor.charging", "charging")
    clock.set("sensor.charger_power", 7.0, "kW")
    start(clock)
    for m in range(60):
        if cloud and 20 <= m < 40:
            clock.house(solar=1.0, battery=6.4, grid=0.0, load=7.4)
        else:
            clock.house(solar=9.0, battery=0.0, grid=-1.6, load=7.4)
        clock.step()


async def test_a_sunny_charge_gets_a_receipt_split_by_source(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    events = []
    hass.bus.async_listen(EVENT_CHARGE, lambda e: events.append(e.data))
    entry.runtime_data.home.add(10, 0.75, 0)  # the Powerwall holds 10 kWh that cost 7.5p each
    sunny_charge(clock)
    clock.set("sensor.charging", "complete")
    clock.set("sensor.battery_level", 54)
    clock.step()
    await hass.async_block_till_done()
    r = entry.runtime_data.last_charge
    assert r["kwh"] == approx(7.0, abs=0.05)
    # 40 minutes all solar, 20 minutes 6.4/7.4 Powerwall and 1/7.4 solar
    assert r["energy"]["battery"] == approx(7 * 20 / 60 * 6.4 / 7.4, abs=0.02)
    assert r["energy"]["grid"] == approx(0.0, abs=0.001)
    assert r["cost"] == approx(r["energy"]["solar"] * 0.09 + r["energy"]["battery"] * 0.075, abs=0.002)
    assert r["soc_start"] == 41 and r["soc_end"] == 54
    assert events and events[0]["kwh"] == r["kwh"] and "curve" not in events[0]
    st = hass.states.get("sensor.clockwatch_model_3_last_charge")
    assert float(st.state) == r["kwh"] and st.attributes["solar_share"] == r["solar_share"]
    assert entry.runtime_data.car.kwh == approx(r["kwh"]) and entry.runtime_data.car.solar_share == approx(r["solar_share"], abs=0.001)


async def test_energy_reported_by_the_car_sets_the_total(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    sunny_charge(clock, cloud=False)
    clock.set("sensor.charge_energy_added", 7.7, "kWh")
    clock.set("sensor.charging", "complete")
    clock.step()
    assert entry.runtime_data.last_charge["kwh"] == approx(7.7, abs=0.001)
    assert entry.runtime_data.last_charge["solar_share"] == approx(1.0)


async def test_overnight_grid_charge_follows_the_half_hourly_price(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    clock.set("sensor.charging", "charging")
    clock.set("sensor.charger_power", 7.0, "kW")
    clock.house(solar=0, battery=0, grid=7.4, load=7.4)
    start(clock)
    clock.set(IMPORT, 0.075, "GBP/kWh")
    clock.step(30)
    clock.set(IMPORT, 0.30, "GBP/kWh")
    clock.step(30)
    clock.set("sensor.charging", "complete")
    clock.step()
    r = entry.runtime_data.last_charge
    assert r["grid_share"] == approx(1.0) and r["cost"] == approx(7 * 0.5 * 0.075 + 7 * 0.5 * 0.30, abs=0.01)


async def test_a_short_stop_inside_a_charge_is_one_receipt(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    clock.set("sensor.charging", "charging")
    clock.set("sensor.charger_power", 7.0, "kW")
    clock.house(0, 0, 7.4, 7.4)
    start(clock)
    clock.step(30)
    clock.set("sensor.charging", "stopped")
    clock.set("sensor.charger_power", 0, "kW")
    clock.step(40)  # a gap in the cheap-rate slots
    clock.set("sensor.charging", "charging")
    clock.set("sensor.charger_power", 7.0, "kW")
    clock.step(30)
    clock.set("sensor.charging", "complete")
    clock.step()
    assert len(entry.runtime_data.charges) == 1 and entry.runtime_data.last_charge["kwh"] == approx(7.0, abs=0.15)


async def test_stopped_for_an_hour_ends_the_charge(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    clock.set("sensor.charging", "charging")
    clock.set("sensor.charger_power", 7.0, "kW")
    clock.house(0, 0, 7.4, 7.4)
    start(clock)
    clock.step(10)
    clock.set("sensor.charging", "stopped")
    clock.step(61)
    assert len(entry.runtime_data.charges) == 1 and entry.runtime_data.charge is None


async def test_solar_counted_as_free(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry(solar_value="free")
    clock = Clock(hass, entry)
    sunny_charge(clock, cloud=False)
    clock.set("sensor.charging", "complete")
    clock.step()
    assert entry.runtime_data.last_charge["cost"] == approx(0.0, abs=0.0001)


async def test_no_home_energy_sensors_counts_everything_as_grid(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry(solar_power_entity=None, battery_power_entity=None, grid_power_entity=None, load_power_entity=None)
    clock = Clock(hass, entry)
    sunny_charge(clock)
    clock.set("sensor.charging", "complete")
    clock.step()
    assert entry.runtime_data.last_charge["grid_share"] == approx(1.0)


def drive(clock: Clock, miles: float, kwh: float, minutes: int = 29, top: float = 52) -> None:
    clock.set("sensor.shift_state", "d")
    start(clock)
    odo0 = float(clock.hass.states.get("sensor.odometer").state)
    e0 = float(clock.hass.states.get("sensor.energy_remaining").state)
    for m in range(minutes):
        clock.set("sensor.speed", top if m == minutes // 2 else 30, "mph")
        clock.step()
    clock.set("sensor.odometer", odo0 + miles, "mi")
    clock.set("sensor.energy_remaining", e0 - kwh, "kWh")
    clock.set("sensor.shift_state", "p")
    clock.step(6)


async def test_a_drive_gets_a_receipt_costed_from_what_charged_the_car(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    t = entry.runtime_data
    t.car.add(40.0, 3.0, 24.0)  # what is in the car: 7.5p a kWh, 60% sunshine
    clock = Clock(hass, entry)
    events = []
    hass.bus.async_listen(EVENT_TRIP, lambda e: events.append(e.data))
    clock.set("device_tracker.location", "home")
    clock.set("sensor.shift_state", "d")
    start(clock)
    clock.set("device_tracker.location", "work")
    drive(clock, 14.2, 3.4)
    await hass.async_block_till_done()
    r = t.last_trip
    assert r["from"] == "Home" and r["to"] == "Work" and r["compare_name"] == "the X3 M40i"
    assert r["miles"] == approx(14.2) and r["kwh"] == approx(3.4) and r["cost"] == approx(0.255)
    assert r["sunshine"] == approx(0.6) and r["max_mph"] == 52 and r["outside_temp"] == 9
    assert r["petrol_cost"] == approx(4.09, abs=0.01) and r["saved"] == approx(3.83, abs=0.01)
    assert r["minutes"] == approx(29, abs=1)
    assert events and events[0]["miles"] == approx(14.2)
    st = hass.states.get("sensor.clockwatch_model_3_last_trip")  # shown in the house's units (kilometres in tests)
    assert float(st.state) == approx(14.2 * 1.609344, abs=0.01) and st.attributes["miles"] == approx(14.2)


async def test_a_short_shuffle_gets_no_receipt_but_its_energy_is_counted(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    t = entry.runtime_data
    t.car.add(40.0, 3.0, 24.0)
    clock = Clock(hass, entry)
    drive(clock, 0.4, 0.2, minutes=3)
    assert t.trips == [] and t.car.kwh == approx(39.8)


async def test_a_short_stop_in_a_drive_is_one_trip(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    clock.set("sensor.shift_state", "d")
    start(clock)
    clock.step(10)
    clock.set("sensor.shift_state", "p")
    clock.step(3)  # a quick stop at the shop
    clock.set("sensor.shift_state", "d")
    clock.step(10)
    clock.set("sensor.odometer", 1009.0, "mi")
    clock.set("sensor.energy_remaining", 21.4, "kWh")
    clock.set("sensor.shift_state", "p")
    clock.step(6)
    assert len(entry.runtime_data.trips) == 1 and entry.runtime_data.last_trip["miles"] == approx(9.0)


async def test_month_sensors_and_the_receipts_action(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    t = entry.runtime_data
    clock = Clock(hass, entry)
    sunny_charge(clock, cloud=False)
    clock.set("sensor.charging", "complete")
    clock.step()
    drive(clock, 14.2, 3.4)
    await hass.async_block_till_done()
    month = t.month(clock.now)
    assert month["charges"] == 1 and month["trips"] == 1 and month["solar_share"] == approx(1.0)
    r = await hass.services.async_call(
        DOMAIN, "history", {"kind": "both", "limit": 5, "month": clock.now.strftime("%Y-%m")}, blocking=True, return_response=True
    )
    assert len(r["charges"]) == 1 and len(r["trips"]) == 1 and r["month"]["miles"] == approx(14.2)


async def test_a_charge_in_progress_survives_a_restart(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    clock.set("sensor.charging", "charging")
    clock.set("sensor.charger_power", 7.0, "kW")
    clock.house(0, 0, 7.4, 7.4)
    start(clock)
    clock.step(30)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.charge is not None and entry.runtime_data.charge.total_kwh == approx(3.5, abs=0.01)


async def test_home_battery_remembers_what_charged_it(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    start(clock)
    clock.house(solar=0, battery=-5.0, grid=5.4, load=0.4)  # Powerwall charging 5 kW from the grid at 7.5p
    clock.step(60)
    home = entry.runtime_data.home
    assert home.kwh == approx(5.0, abs=0.01) and home.unit_cost == approx(0.075, abs=0.0001) and home.solar_share == approx(0.0)
    clock.set(EXPORT, 0.09, "GBP/kWh")
    clock.house(solar=6.0, battery=-5.0, grid=-0.6, load=0.4)  # then from spare sunshine, valued at 9p
    clock.step(60)
    assert home.kwh == approx(10.0, abs=0.02) and home.unit_cost == approx(0.0825, abs=0.0005) and home.solar_share == approx(0.5, abs=0.01)


async def test_away_from_any_zone_is_just_away(hass: HomeAssistant, setup_entry) -> None:
    entry = await setup_entry()
    clock = Clock(hass, entry)
    clock.set("device_tracker.location", "not_home")
    drive(clock, 5.0, 1.2)
    assert entry.runtime_data.last_trip["from"] == "Away" and entry.runtime_data.last_trip["to"] == "Away"
