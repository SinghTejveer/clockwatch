# Changelog

## 0.2.0 (20 October 2026)

First public release.

- **Receipts for every charge**: energy split minute by minute into solar, home battery and grid; cost from your electricity price for each half hour (Octopus rate sensors work as they are); solar valued at the export price you gave up, or free; range added and cost per mile.
- **Receipts for every drive over a mile**: distance, time, speeds, energy, efficiency, cost from what actually charged the car, the share of sunshine in the battery, and what your petrol car would have cost. Trips name the zones they started and ended in.
- **This month**: charging cost, solar share, miles, cost per mile and the saving against petrol, as sensors.
- **Three dashboard cards**, loaded automatically: charge (charging curve, classic, pump display, minimal), trip (boarding pass, till roll, route strip, scorecard) and month. Step back through older receipts with the arrows.
- **Events** `clockwatch_charge_finished` and `clockwatch_trip_finished`, and the `clockwatch.history` action.
- Cars: Teslemetry.
