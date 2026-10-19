"""Watching the car and the house: charges and trips as they happen, the receipts when they end, and what they are saved as."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_LEVEL,
    CONF_BATTERY_POWER,
    CONF_CAPACITY,
    CONF_CHARGER_POWER,
    CONF_CHARGING_STATE,
    CONF_COMPARE_ECONOMY,
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
    DEFAULT_EXPORT_PRICE,
    DEFAULT_FUEL_PRICE,
    DEFAULT_IMPORT_PRICE,
    DEFAULT_MI_PER_KWH,
    DEFAULT_MIN_TRIP_MILES,
    DOMAIN,
    ECONOMY_MPG_UK,
    EVENT_CHARGE,
    EVENT_TRIP,
    KM_PER_MILE,
    MAX_HISTORY,
    PARKED_MINUTES,
    PAUSE_MINUTES,
    SAMPLE_SECONDS,
    SOLAR_FREE,
    SRC_GRID,
    SRC_SOLAR,
    STORAGE_VERSION,
)
from .ledger import ChargeSession, StoreLedger, TripSession, battery_charge_sources, month_summary, supply_shares

_LOGGER = logging.getLogger(__name__)

CHARGING = ("charging", "starting")
CHARGE_OVER = ("complete", "disconnected", "no_power")
MAX_GAP_H = 5 / 60  # a gap longer than this between samples is not counted (Home Assistant was down)


def signal(entry_id: str) -> str:
    return f"{DOMAIN}_update_{entry_id}"


class Tracker:
    """Everything Clockwatch knows about one car."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.charges: list[dict[str, Any]] = []
        self.trips: list[dict[str, Any]] = []
        self.car = StoreLedger(capacity=self.capacity)
        self.home = StoreLedger()
        self.charge: ChargeSession | None = None
        self.trip: TripSession | None = None
        self.paused_at: str | None = None
        self.parked_at: str | None = None
        self.last_sample: datetime | None = None
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------ settings
    @property
    def conf(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def capacity(self) -> float:
        return float(self.conf.get(CONF_CAPACITY) or DEFAULT_CAPACITY)

    # ------------------------------------------------ saving
    async def async_load(self) -> None:
        d = await self.store.async_load() or {}
        self.charges = list(d.get("charges") or [])
        self.trips = list(d.get("trips") or [])
        self.car = StoreLedger.from_dict(d.get("car"), self.capacity)
        self.home = StoreLedger.from_dict(d.get("home"))
        self.charge = ChargeSession.from_dict(d["charge"]) if d.get("charge") else None
        self.trip = TripSession.from_dict(d["trip"]) if d.get("trip") else None
        self.paused_at = d.get("paused_at")
        self.parked_at = d.get("parked_at")

    def _data(self) -> dict[str, Any]:
        return {
            "charges": self.charges[-MAX_HISTORY:],
            "trips": self.trips[-MAX_HISTORY:],
            "car": self.car.to_dict(),
            "home": self.home.to_dict(),
            "charge": self.charge.to_dict() if self.charge else None,
            "trip": self.trip.to_dict() if self.trip else None,
            "paused_at": self.paused_at,
            "parked_at": self.parked_at,
        }

    def save(self, now: bool = False) -> None:
        if now:
            self.hass.async_create_task(self.store.async_save(self._data()))
        else:
            self.store.async_delay_save(self._data, 30)

    async def async_flush(self) -> None:
        await self.store.async_save(self._data())

    # ------------------------------------------------ reading sensors
    def _state(self, key: str) -> str | None:
        eid = self.conf.get(key)
        st = self.hass.states.get(eid) if eid else None
        if st is None or st.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None
        return st.state

    def _num(self, key: str) -> float | None:
        eid = self.conf.get(key)
        st = self.hass.states.get(eid) if eid else None
        if st is None:
            return None
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            return None
        unit = str(st.attributes.get("unit_of_measurement") or "").strip()
        low = unit.lower()
        if low in ("w", "wh"):
            return v / 1000.0
        if low in ("mw", "mwh"):
            return v * 1000.0
        if low == "km":
            return v / KM_PER_MILE
        if low == "km/h":
            return v / KM_PER_MILE
        if low.startswith(("p/", "pence", "gbx")):
            return v / 100.0
        return v

    def _price(self, entity_key: str, fixed_key: str, default: float) -> float:
        v = self._num(entity_key) if self.conf.get(entity_key) else None
        if v is None:
            v = self.conf.get(fixed_key)
        return float(default if v is None else v)

    def import_price(self) -> float:
        return self._price(CONF_IMPORT_PRICE_ENTITY, CONF_IMPORT_PRICE, DEFAULT_IMPORT_PRICE)

    def solar_value(self) -> float:
        if self.conf.get(CONF_SOLAR_VALUE) == SOLAR_FREE:
            return 0.0
        return self._price(CONF_EXPORT_PRICE_ENTITY, CONF_EXPORT_PRICE, DEFAULT_EXPORT_PRICE)

    def kwh_per_mile(self) -> float:
        """From the last 20 trips with a reading, else a typical 3.5 mi/kWh."""
        miles = sum(t["miles"] for t in self.trips[-20:] if t.get("kwh"))
        kwh = sum(t["kwh"] for t in self.trips[-20:] if t.get("kwh"))
        return kwh / miles if miles > 5 and kwh > 0 else 1 / DEFAULT_MI_PER_KWH

    # ------------------------------------------------ running
    @callback
    def async_start(self) -> None:
        watched = [e for e in (self.conf.get(CONF_CHARGING_STATE), self.conf.get(CONF_SHIFT_STATE)) if e]
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._changed))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=SAMPLE_SECONDS)))

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        self.sample(dt_util.now())
        self.check(dt_util.now())

    async def _tick(self, now: datetime) -> None:
        self.sample(now)
        self.check(now)

    def sample(self, now: datetime) -> None:
        """One step: the energy that moved since the last sample, into the home battery, the car, and the running charge."""
        hours = (now - self.last_sample).total_seconds() / 3600 if self.last_sample else 0.0
        self.last_sample = now
        if hours <= 0 or hours > MAX_GAP_H:
            return
        solar, batt, grid, load = (self._num(k) for k in (CONF_SOLAR_POWER, CONF_BATTERY_POWER, CONF_GRID_POWER, CONF_LOAD_POWER))
        price, solar_value = self.import_price(), self.solar_value()
        if batt is not None and batt < 0:  # the home battery is charging: what it stores, and what that cost
            src = battery_charge_sources(solar, batt, load)
            kwh = -batt * hours
            self.home.add(kwh, kwh * (src[SRC_SOLAR] * solar_value + src[SRC_GRID] * price), kwh * src[SRC_SOLAR])
        elif batt is not None and batt > 0:
            self.home.take(batt * hours)
        charging = (self._state(CONF_CHARGING_STATE) or "").lower() in CHARGING
        if self.charge is not None and self.paused_at is None and charging:
            car_kw = self._num(CONF_CHARGER_POWER) or 0.0
            minutes = (now - dt_util.parse_datetime(self.charge.started)).total_seconds() / 60
            shares = supply_shares(solar, batt, grid, load)
            self.charge.add(minutes, hours, car_kw, shares, price, solar_value, self.home.unit_cost if self.home.unit_cost is not None else price)
        if self.trip is not None:
            speed = self._num(CONF_SPEED)
            if speed is not None:
                self.trip.max_speed = max(self.trip.max_speed, speed)
        self.save()

    def check(self, now: datetime) -> None:
        """Start and end charges and trips from the car's state."""
        state = (self._state(CONF_CHARGING_STATE) or "").lower()
        if state in CHARGING:
            if self.charge is None:
                self.charge = ChargeSession(now.isoformat(), soc_start=self._num(CONF_BATTERY_LEVEL))
                _LOGGER.debug("Charge started")
            self.paused_at = None
        elif self.charge is not None:
            if state in CHARGE_OVER:
                self.finish_charge(now)
            elif self.paused_at is None:
                self.paused_at = now.isoformat()
            elif now - dt_util.parse_datetime(self.paused_at) >= timedelta(minutes=PAUSE_MINUTES):
                self.finish_charge(now)

        gear = (self._state(CONF_SHIFT_STATE) or "").lower()
        if gear in ("d", "r", "n"):
            if self.trip is None:
                odo = self._num(CONF_ODOMETER)
                if odo is not None:
                    self.trip = TripSession(
                        now.isoformat(), odo, self._num(CONF_ENERGY_REMAINING), self._num(CONF_BATTERY_LEVEL), outside_temp=self._num(CONF_OUTSIDE_TEMP)
                    )
            self.parked_at = None
        elif self.trip is not None and gear == "p":
            if self.parked_at is None:
                self.parked_at = now.isoformat()
            elif now - dt_util.parse_datetime(self.parked_at) >= timedelta(minutes=PARKED_MINUTES):
                self.finish_trip(now)

    # ------------------------------------------------ receipts
    def finish_charge(self, now: datetime) -> dict[str, Any] | None:
        session, self.charge, self.paused_at = self.charge, None, None
        if session is None:
            return None
        receipt = session.finish(
            now.isoformat(), self._num(CONF_ENERGY_ADDED), self._num(CONF_BATTERY_LEVEL), self.kwh_per_mile(), self.conf.get(CONF_SOLAR_VALUE) == SOLAR_FREE
        )
        if receipt["kwh"] < 0.05:
            self.save(now=True)
            return None
        self.car.add(receipt["kwh"], receipt["cost"], receipt["energy"][SRC_SOLAR])
        self.charges.append(receipt)
        self.charges = self.charges[-MAX_HISTORY:]
        self.hass.bus.async_fire(EVENT_CHARGE, {"entry_id": self.entry.entry_id, **{k: v for k, v in receipt.items() if k != "curve"}})
        async_dispatcher_send(self.hass, signal(self.entry.entry_id))
        self.save(now=True)
        return receipt

    def finish_trip(self, now: datetime) -> dict[str, Any] | None:
        session, self.trip, self.parked_at = self.trip, None, None
        if session is None:
            return None
        odo = self._num(CONF_ODOMETER)
        if odo is None:
            return None
        minutes = (now - dt_util.parse_datetime(session.started)).total_seconds() / 60 - PARKED_MINUTES
        receipt = session.finish(
            now.isoformat(),
            odo,
            self._num(CONF_ENERGY_REMAINING),
            self._num(CONF_BATTERY_LEVEL),
            self.capacity,
            max(minutes, 0.0),
            self.car,
            self.import_price(),
            float(self.conf.get(CONF_COMPARE_ECONOMY) or DEFAULT_COMPARE_ECONOMY),
            self.conf.get(CONF_COMPARE_UNIT) or ECONOMY_MPG_UK,
            float(self.conf.get(CONF_FUEL_PRICE) or DEFAULT_FUEL_PRICE),
        )
        if receipt["miles"] < float(self.conf.get(CONF_MIN_TRIP_MILES) or DEFAULT_MIN_TRIP_MILES):
            self.save(now=True)  # the energy was still used; no receipt for a short shuffle
            return None
        self.trips.append(receipt)
        self.trips = self.trips[-MAX_HISTORY:]
        self.hass.bus.async_fire(EVENT_TRIP, {"entry_id": self.entry.entry_id, **receipt})
        async_dispatcher_send(self.hass, signal(self.entry.entry_id))
        self.save(now=True)
        return receipt

    # ------------------------------------------------ what the sensors and cards read
    @property
    def last_charge(self) -> dict[str, Any] | None:
        return self.charges[-1] if self.charges else None

    @property
    def last_trip(self) -> dict[str, Any] | None:
        return self.trips[-1] if self.trips else None

    def month(self, when: datetime | None = None) -> dict[str, Any]:
        return month_summary(self.charges, self.trips, (when or dt_util.now()).strftime("%Y-%m"))
