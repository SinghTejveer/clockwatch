"""The arithmetic, checked against worked examples. Pure: no Home Assistant."""

import pytest

from custom_components.clockwatch.const import ECONOMY_L100KM, ECONOMY_MPG_UK, ECONOMY_MPG_US
from custom_components.clockwatch.ledger import (
    ChargeSession,
    StoreLedger,
    TripSession,
    battery_charge_sources,
    month_summary,
    petrol_cost,
    supply_shares,
)

approx = pytest.approx


# ---------------------------------------------------------------- where the house's power comes from
def test_sunny_afternoon_all_solar():
    # 7.4 kW load (car 7 + house 0.4), panels making 9, exporting 1.6
    assert supply_shares(9.0, 0.0, -1.6, 7.4) == {"solar": approx(1.0), "battery": approx(0.0), "grid": approx(0.0)}


def test_cloud_powerwall_fills_the_gap():
    # 7.4 kW load, solar 5.3, Powerwall discharging 2.1
    s = supply_shares(5.3, 2.1, 0.0, 7.4)
    assert s["battery"] == approx(2.1 / 7.4) and s["solar"] == approx(5.3 / 7.4) and s["grid"] == approx(0.0)


def test_night_all_grid_even_while_the_powerwall_charges():
    # importing 12 kW: 7.4 for the house and car, 4.6 into the Powerwall
    assert supply_shares(0.0, -4.6, 12.0, 7.4) == {"solar": 0.0, "battery": 0.0, "grid": approx(1.0)}


def test_mixed_three_ways_add_up_to_one():
    s = supply_shares(2.0, 1.0, 4.4, 7.4)
    assert sum(s.values()) == approx(1.0) and s["grid"] == approx(4.4 / 7.4)


def test_no_home_energy_sensors_means_grid():
    assert supply_shares(None, None, None, None) == {"solar": 0.0, "battery": 0.0, "grid": 1.0}


def test_home_battery_charging_from_spare_solar_then_grid():
    assert battery_charge_sources(6.0, -3.0, 1.0) == {"solar": approx(1.0), "grid": approx(0.0)}
    assert battery_charge_sources(2.0, -3.0, 1.0) == {"solar": approx(1 / 3), "grid": approx(2 / 3)}
    assert battery_charge_sources(0.0, 2.0, 1.0) == {"solar": 0.0, "grid": 0.0}


# ---------------------------------------------------------------- what is stored in a battery
def test_store_averages_cost_and_sunshine():
    s = StoreLedger()
    s.add(10, 0.75, 0)  # 10 kWh at 7.5p from the grid
    s.add(10, 0.90, 10)  # 10 kWh of solar valued at 9p
    assert s.unit_cost == approx(0.0825) and s.solar_share == approx(0.5)
    cost, share = s.take(4)
    assert cost == approx(0.33) and share == approx(0.5)
    assert s.kwh == approx(16) and s.unit_cost == approx(0.0825), "taking energy keeps the average"


def test_store_with_nothing_recorded_uses_the_fallback_price():
    cost, share = StoreLedger().take(3, fallback_unit_cost=0.25)
    assert cost == approx(0.75) and share is None


def test_store_never_holds_more_than_its_capacity():
    s = StoreLedger(capacity=50)
    s.add(40, 4.0, 0)
    s.add(20, 0.0, 20)
    assert s.kwh == approx(50) and s.unit_cost == approx(4.0 / 60) and s.solar_share == approx(20 / 60)


def test_store_round_trip():
    s = StoreLedger(12.5, 1.2, 3.0)
    assert StoreLedger.from_dict(s.to_dict()) == s


# ---------------------------------------------------------------- a charge
def solar_afternoon():
    c = ChargeSession("2026-10-19T13:05:00+01:00", soc_start=41)
    for m in range(100):  # 100 minutes at 5.76 kW = 9.6 kWh
        shares = {"solar": 1.0, "battery": 0.0, "grid": 0.0} if not 40 <= m < 62 else {"solar": 0.0, "battery": 1.0, "grid": 0.0}
        c.add(m, 1 / 60, 5.76, shares, import_price=0.30, solar_value=0.09, battery_unit_cost=0.075)
    return c


def test_charge_split_and_cost():
    r = solar_afternoon().finish("2026-10-19T14:45:00+01:00", None, 77, kwh_per_mile=1 / 4, solar_free_cost=False)
    assert r["kwh"] == approx(9.6, abs=0.01)
    assert r["energy"]["battery"] == approx(5.76 * 22 / 60, abs=0.01) and r["energy"]["grid"] == 0
    assert r["cost"] == approx(r["energy"]["solar"] * 0.09 + r["energy"]["battery"] * 0.075, abs=0.001)
    assert r["cost_if_solar_free"] == approx(r["energy"]["battery"] * 0.075, abs=0.001)
    assert r["miles_added"] == approx(38.4, abs=0.1) and r["cost_per_mile"] == approx(r["cost"] / 38.4, rel=0.01)
    assert r["solar_share"] + r["battery_share"] + r["grid_share"] == approx(1.0, abs=0.001)
    assert len(r["curve"]) == 100 and r["curve"][45][3] == 1.0


def test_charge_scaled_to_the_energy_the_car_reports_keeping_proportions():
    c = solar_afternoon()
    r = c.finish("x", energy_added=10.56, soc_end=77, kwh_per_mile=None, solar_free_cost=False)
    assert r["kwh"] == approx(10.56, abs=0.001)
    assert r["solar_share"] == approx(c.energy["solar"] / c.total_kwh, abs=0.001)
    assert r["miles_added"] is None


def test_overnight_grid_charge_priced_by_the_half_hour():
    c = ChargeSession("2026-10-18T23:30:00+01:00")
    grid = {"solar": 0.0, "battery": 0.0, "grid": 1.0}
    for m in range(60):
        c.add(m, 1 / 60, 7.0, grid, import_price=0.075 if m < 30 else 0.30, solar_value=0.09, battery_unit_cost=0.0)
    r = c.finish("x", None, None, None, False)
    assert r["cost"] == approx(3.5 * 0.075 + 3.5 * 0.30, abs=0.001)


def test_zero_power_or_time_adds_nothing():
    c = ChargeSession("x")
    c.add(0, 1 / 60, 0.0, {"grid": 1.0}, 0.3, 0.09, 0.1)
    c.add(1, 0.0, 7.0, {"grid": 1.0}, 0.3, 0.09, 0.1)
    assert c.total_kwh == 0 and c.samples == []


def test_charge_session_survives_a_restart():
    c = solar_afternoon()
    again = ChargeSession.from_dict(c.to_dict())
    assert again.energy == c.energy and again.cost == c.cost and again.samples == c.samples


# ---------------------------------------------------------------- petrol
def test_petrol_cost_uk_us_and_metric():
    assert petrol_cost(14.2, 30, ECONOMY_MPG_UK, 1.90) == approx(4.09, abs=0.01)
    assert petrol_cost(30, 30, ECONOMY_MPG_US, 1.0) == approx(3.785, abs=0.001)
    assert petrol_cost(62.137, 6.0, ECONOMY_L100KM, 1.0) == approx(6.0, abs=0.01)
    assert petrol_cost(0, 30, ECONOMY_MPG_UK, 1.9) == 0


# ---------------------------------------------------------------- a trip
def test_trip_from_energy_remaining_costed_from_the_car_battery():
    car = StoreLedger(40.0, 3.0, 24.0)  # 7.5p a kWh, 60% sunshine
    t = TripSession("2026-10-19T08:12:00+01:00", 1000.0, 50.0, 80.0, max_speed=52, outside_temp=9)
    r = t.finish("2026-10-19T08:41:00+01:00", 1014.2, 46.6, 74.0, 57.5, 29, car, 0.25, 30, ECONOMY_MPG_UK, 1.90)
    assert r["miles"] == approx(14.2) and r["kwh"] == approx(3.4) and r["miles_per_kwh"] == approx(4.18, abs=0.01)
    assert r["cost"] == approx(0.255) and r["sunshine"] == approx(0.6)
    assert r["petrol_cost"] == approx(4.09, abs=0.01) and r["saved"] == approx(4.09 - 0.255, abs=0.01)
    assert r["avg_mph"] == approx(29.4, abs=0.1) and r["max_mph"] == 52
    assert car.kwh == approx(36.6)


def test_trip_falls_back_to_battery_percentage():
    r = TripSession("a", 0.0, None, 80.0).finish("b", 10.0, None, 70.0, 60.0, 20, StoreLedger(), 0.2, 40, ECONOMY_MPG_UK, 1.5)
    assert r["kwh"] == approx(6.0) and r["cost"] == approx(1.2) and r["sunshine"] is None


def test_trip_round_trip():
    t = TripSession("a", 12.5, 40.0, 70.0, 33.0, 8.0)
    assert TripSession.from_dict(t.to_dict()) == t


# ---------------------------------------------------------------- a month
def test_month_summary_counts_only_that_month():
    ch = [
        {"ended": "2026-10-03T07:00", "kwh": 20.0, "energy": {"solar": 5.0}, "cost": 1.5},
        {"ended": "2026-10-19T14:45", "kwh": 10.0, "energy": {"solar": 7.0}, "cost": 0.8},
        {"ended": "2026-09-30T07:00", "kwh": 30.0, "energy": {"solar": 0.0}, "cost": 9.0},
    ]
    tr = [{"ended": "2026-10-19T08:41", "miles": 14.2, "cost": 0.26, "petrol_cost": 4.09}]
    m = month_summary(ch, tr, "2026-10")
    assert m["charges"] == 2 and m["charge_kwh"] == 30.0 and m["solar_share"] == approx(0.4) and m["charge_cost"] == 2.3
    assert m["miles"] == 14.2 and m["saved"] == approx(3.83) and m["cost_per_mile"] == approx(0.0183, abs=0.0001)


def test_empty_month():
    m = month_summary([], [], "2026-11")
    assert m["charges"] == 0 and m["solar_share"] is None and m["cost_per_mile"] is None
