# Clockwatch

**Every charge and every drive, itemised.**

Receipts for every EV charge and drive in Home Assistant: where each charge's energy came from (solar, home battery or grid), what it cost, the cost per mile, and what the same drive would have cost in a petrol car.

> Status: early development (0.1). The dashboard cards, with a choice of styles, arrive in 0.2. Screenshots of every card style will be here.

## What you get

- **A receipt for every charge**: energy split into solar, home battery and grid, minute by minute; cost from your electricity price for each half hour (Octopus rate sensors work as they are); solar valued at the export price you gave up, or free; miles added and cost per mile.
- **A receipt for every drive over a mile**: distance, time, speeds, energy, efficiency, cost (from what charged the car), the share of sunshine in the battery, and the petrol comparison.
- **This month**: charging cost, solar share, miles, cost per mile, and money saved against petrol.
- **Events** `clockwatch_charge_finished` and `clockwatch_trip_finished` for your own automations, and a `clockwatch.history` action that returns recent receipts.

## How it works it out

- While the car charges, its share of the house's power is split the way the house is being supplied at that minute: home battery first, then the grid, and solar for the rest.
- The home battery remembers what charged it (sunshine at the export price, grid at its price), so energy taken from it is costed at that average.
- The car's battery is tracked the same way, so a drive is costed at what actually charged the car, and its "sunshine" is the solar share of that energy.
- A charge that stops for less than an hour (a gap between cheap-rate slots) stays one charge. A drive ends after 5 minutes in Park.

## Supported cars

| Integration | Status |
| --- | --- |
| [Teslemetry](https://www.home-assistant.io/integrations/teslemetry/) | Supported |
| Other cars with charging, odometer and gear sensors | Planned |

Teslemetry switches some sensors off by default. Clockwatch needs **charging state, charger power, odometer and shift state**, and works best with **energy remaining** and **battery level**; setup tells you which are off.

## Install

1. HACS → menu → Custom repositories → add `https://github.com/SinghTejveer/clockwatch` as an **Integration**.
2. Install **Clockwatch** and restart Home Assistant.
3. Settings → Devices & services → Add integration → **Clockwatch**: choose the car; the car, home-energy and Octopus price sensors are found for you; set the petrol car to compare with.

## Privacy

Everything is worked out and stored in your Home Assistant. Clockwatch keeps no locations and sends nothing anywhere.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## Licence

MIT
