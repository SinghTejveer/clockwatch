"""The arithmetic of Clockwatch: pure functions and small classes, no Home Assistant, no clock.

How a charge is split and priced
    Every minute the house is supplied by some mix of solar, the home battery and the grid. While the car charges, its share of the house's
    power is split in the same proportions (`supply_shares`). Grid energy is priced at the import rate for that minute; solar at the export
    price you gave up (or nothing); home-battery energy at the average cost of what is stored in it (`StoreLedger`).

What a trip costs
    The car's battery is a `StoreLedger` too: each charge adds energy with its cost and its solar share, each drive takes energy out at the
    average cost and solar share of what is in it. So a trip's cost and "sunshine" come from the charges that filled the battery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    ECONOMY_L100KM,
    ECONOMY_MPG_UK,
    ECONOMY_MPG_US,
    KM_PER_MILE,
    LITRES_PER_UK_GALLON,
    LITRES_PER_US_GALLON,
    SOURCES,
    SRC_BATTERY,
    SRC_GRID,
    SRC_SOLAR,
)

Shares = dict[str, float]


def supply_shares(solar_kw: float | None, battery_kw: float | None, grid_kw: float | None, load_kw: float | None) -> Shares:
    """How the house is being supplied right now, as shares of 1: solar, home battery, grid.

    battery_kw > 0 means the home battery is discharging; grid_kw > 0 means importing. With no home-energy sensors everything is grid.
    Solar covers what the battery and grid do not, so the three always add up to 1.
    """
    if solar_kw is None and battery_kw is None and grid_kw is None:
        return {SRC_SOLAR: 0.0, SRC_BATTERY: 0.0, SRC_GRID: 1.0}
    load = max(0.0, load_kw or 0.0)
    if load <= 0.001:
        return {SRC_SOLAR: 0.0, SRC_BATTERY: 0.0, SRC_GRID: 1.0}
    batt = min(load, max(0.0, battery_kw or 0.0))
    grid = min(load - batt, max(0.0, grid_kw or 0.0))
    solar = max(0.0, load - batt - grid)
    return {SRC_SOLAR: solar / load, SRC_BATTERY: batt / load, SRC_GRID: grid / load}


def battery_charge_sources(solar_kw: float | None, battery_kw: float | None, load_kw: float | None) -> Shares:
    """Where the home battery's charge is coming from while it charges (battery_kw < 0): spare solar first, the rest from the grid."""
    charging = max(0.0, -(battery_kw or 0.0))
    if charging <= 0:
        return {SRC_SOLAR: 0.0, SRC_GRID: 0.0}
    spare_solar = max(0.0, (solar_kw or 0.0) - max(0.0, load_kw or 0.0))
    solar = min(charging, spare_solar)
    return {SRC_SOLAR: solar / charging, SRC_GRID: (charging - solar) / charging}


@dataclass
class StoreLedger:
    """Energy in a battery, with what it cost and how much of it was sunshine. Energy leaves at the average of what is in it."""

    kwh: float = 0.0
    cost: float = 0.0
    solar_kwh: float = 0.0
    capacity: float | None = None

    def add(self, kwh: float, cost: float, solar_kwh: float) -> None:
        if kwh <= 0:
            return
        self.kwh += kwh
        self.cost += cost
        self.solar_kwh += solar_kwh
        if self.capacity and self.kwh > self.capacity:  # the oldest energy has gone; keep the averages, trim the amount
            f = self.capacity / self.kwh
            self.kwh, self.cost, self.solar_kwh = self.capacity, self.cost * f, self.solar_kwh * f

    @property
    def unit_cost(self) -> float | None:
        return self.cost / self.kwh if self.kwh > 0 else None

    @property
    def solar_share(self) -> float | None:
        return self.solar_kwh / self.kwh if self.kwh > 0 else None

    def take(self, kwh: float, fallback_unit_cost: float = 0.0) -> tuple[float, float | None]:
        """Remove energy -> (its cost, its solar share). With nothing recorded yet, energy is costed at fallback_unit_cost."""
        if kwh <= 0:
            return 0.0, self.solar_share
        unit, share = self.unit_cost, self.solar_share
        if unit is None:
            return kwh * fallback_unit_cost, None
        cost = kwh * unit
        f = min(kwh, self.kwh) / self.kwh
        self.kwh, self.cost, self.solar_kwh = self.kwh * (1 - f), self.cost * (1 - f), self.solar_kwh * (1 - f)
        return cost, share

    def to_dict(self) -> dict[str, Any]:
        return {"kwh": self.kwh, "cost": self.cost, "solar_kwh": self.solar_kwh}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None, capacity: float | None = None) -> StoreLedger:
        d = d or {}
        return cls(float(d.get("kwh", 0.0)), float(d.get("cost", 0.0)), float(d.get("solar_kwh", 0.0)), capacity)


@dataclass
class ChargeSession:
    """One charge, built up a minute at a time."""

    started: str
    soc_start: float | None = None
    energy: Shares = field(default_factory=lambda: dict.fromkeys(SOURCES, 0.0))
    cost: Shares = field(default_factory=lambda: dict.fromkeys(SOURCES, 0.0))
    peak_kw: float = 0.0
    samples: list[list[float]] = field(default_factory=list)  # [minutes since start, kW, solar share, battery share] for the curve

    def add(self, minutes: float, hours: float, car_kw: float, shares: Shares, import_price: float, solar_value: float, battery_unit_cost: float) -> None:
        """Add `hours` of charging at `car_kw`, split by the house's supply `shares`."""
        if hours <= 0 or car_kw <= 0:
            return
        kwh = car_kw * hours
        price = {SRC_SOLAR: solar_value, SRC_BATTERY: battery_unit_cost, SRC_GRID: import_price}
        for s in SOURCES:
            part = kwh * shares.get(s, 0.0)
            self.energy[s] += part
            self.cost[s] += part * price[s]
        self.peak_kw = max(self.peak_kw, car_kw)
        self.samples.append([round(minutes, 1), round(car_kw, 2), round(shares.get(SRC_SOLAR, 0.0), 3), round(shares.get(SRC_BATTERY, 0.0), 3)])

    @property
    def total_kwh(self) -> float:
        return sum(self.energy.values())

    def finish(self, ended: str, energy_added: float | None, soc_end: float | None, kwh_per_mile: float | None, solar_free_cost: bool) -> dict[str, Any]:
        """The receipt. When the car reports the energy it took (energy_added), the split is scaled to it, keeping the proportions."""
        measured = self.total_kwh
        scale = energy_added / measured if energy_added and measured > 0.05 else 1.0
        energy = {s: self.energy[s] * scale for s in SOURCES}
        cost = {s: self.cost[s] * scale for s in SOURCES}
        total = sum(energy.values())
        total_cost = sum(cost.values())
        miles = total / kwh_per_mile if kwh_per_mile and total > 0 else None
        return {
            "started": self.started,
            "ended": ended,
            "kwh": round(total, 3),
            "energy": {s: round(v, 3) for s, v in energy.items()},
            "cost": round(total_cost, 4),
            "cost_by_source": {s: round(v, 4) for s, v in cost.items()},
            "cost_if_solar_free": round(total_cost - cost[SRC_SOLAR], 4) if not solar_free_cost else round(total_cost, 4),
            "solar_share": round(energy[SRC_SOLAR] / total, 4) if total > 0 else 0.0,
            "battery_share": round(energy[SRC_BATTERY] / total, 4) if total > 0 else 0.0,
            "grid_share": round(energy[SRC_GRID] / total, 4) if total > 0 else 0.0,
            "soc_start": self.soc_start,
            "soc_end": soc_end,
            "peak_kw": round(self.peak_kw, 2),
            "miles_added": round(miles, 1) if miles is not None else None,
            "cost_per_mile": round(total_cost / miles, 4) if miles else None,
            "curve": self.samples[-240:],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "soc_start": self.soc_start,
            "energy": self.energy,
            "cost": self.cost,
            "peak_kw": self.peak_kw,
            "samples": self.samples,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChargeSession:
        s = cls(d["started"], d.get("soc_start"))
        s.energy.update(d.get("energy") or {})
        s.cost.update(d.get("cost") or {})
        s.peak_kw = float(d.get("peak_kw") or 0.0)
        s.samples = list(d.get("samples") or [])
        return s


def litres_used(miles: float, economy: float, unit: str) -> float:
    """Fuel a comparison car would burn over `miles`."""
    if economy <= 0 or miles <= 0:
        return 0.0
    if unit == ECONOMY_L100KM:
        return miles * KM_PER_MILE * economy / 100.0
    gallon = LITRES_PER_US_GALLON if unit == ECONOMY_MPG_US else LITRES_PER_UK_GALLON
    return miles / economy * gallon


def petrol_cost(miles: float, economy: float, unit: str = ECONOMY_MPG_UK, price_per_litre: float = 0.0) -> float:
    return litres_used(miles, economy, unit) * price_per_litre


@dataclass
class TripSession:
    """One drive: from leaving Park to being parked for a while."""

    started: str
    odometer_start: float  # miles
    energy_start: float | None  # kWh in the car's battery
    soc_start: float | None
    max_speed: float = 0.0  # mph
    outside_temp: float | None = None

    def finish(
        self,
        ended: str,
        odometer_end: float,
        energy_end: float | None,
        soc_end: float | None,
        capacity: float,
        minutes: float,
        car_store: StoreLedger,
        fallback_unit_cost: float,
        economy: float,
        economy_unit: str,
        fuel_price: float,
    ) -> dict[str, Any]:
        miles = max(0.0, odometer_end - self.odometer_start)
        if self.energy_start is not None and energy_end is not None:
            used = max(0.0, self.energy_start - energy_end)
        elif self.soc_start is not None and soc_end is not None:
            used = max(0.0, (self.soc_start - soc_end) / 100.0 * capacity)
        else:
            used = 0.0
        cost, sunshine = car_store.take(used, fallback_unit_cost)
        petrol = petrol_cost(miles, economy, economy_unit, fuel_price)
        return {
            "started": self.started,
            "ended": ended,
            "miles": round(miles, 2),
            "km": round(miles * KM_PER_MILE, 2),
            "minutes": round(minutes, 1),
            "avg_mph": round(miles / (minutes / 60.0), 1) if minutes > 0 else None,
            "max_mph": round(self.max_speed, 0) if self.max_speed else None,
            "kwh": round(used, 3),
            "miles_per_kwh": round(miles / used, 2) if used > 0.05 else None,
            "cost": round(cost, 4),
            "cost_per_mile": round(cost / miles, 4) if miles > 0 else None,
            "sunshine": round(sunshine, 4) if sunshine is not None else None,
            "soc_start": self.soc_start,
            "soc_end": soc_end,
            "outside_temp": self.outside_temp,
            "petrol_cost": round(petrol, 4),
            "saved": round(petrol - cost, 4),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "odometer_start": self.odometer_start,
            "energy_start": self.energy_start,
            "soc_start": self.soc_start,
            "max_speed": self.max_speed,
            "outside_temp": self.outside_temp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TripSession:
        return cls(d["started"], float(d["odometer_start"]), d.get("energy_start"), d.get("soc_start"), float(d.get("max_speed") or 0.0), d.get("outside_temp"))


def month_summary(charges: list[dict[str, Any]], trips: list[dict[str, Any]], month: str) -> dict[str, Any]:
    """Totals for a calendar month ('2026-10'), from the receipts whose end falls in it."""
    ch = [c for c in charges if str(c.get("ended", "")).startswith(month)]
    tr = [t for t in trips if str(t.get("ended", "")).startswith(month)]
    kwh = sum(c["kwh"] for c in ch)
    solar = sum(c["energy"][SRC_SOLAR] for c in ch)
    cost = sum(c["cost"] for c in ch)
    miles = sum(t["miles"] for t in tr)
    trip_cost = sum(t["cost"] for t in tr)
    petrol = sum(t["petrol_cost"] for t in tr)
    return {
        "month": month,
        "charges": len(ch),
        "charge_kwh": round(kwh, 2),
        "charge_cost": round(cost, 2),
        "solar_share": round(solar / kwh, 4) if kwh > 0 else None,
        "trips": len(tr),
        "miles": round(miles, 1),
        "trip_cost": round(trip_cost, 2),
        "cost_per_mile": round(trip_cost / miles, 4) if miles > 0 else None,
        "petrol_cost": round(petrol, 2),
        "saved": round(petrol - trip_cost, 2),
    }
