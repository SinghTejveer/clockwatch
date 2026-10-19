# Clockwatch

**Every charge and every drive, itemised.**

Receipts for every EV charge and drive in Home Assistant: where each charge's energy came from (solar, home battery or grid), what it cost, the cost per mile, and what the same drive would have cost in a petrol car.

<p><img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/charge-curve.png" alt="The charge card: a charging curve coloured by solar, home battery and grid, with cost, cost per mile, range added and solar share" width="360"> <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/trip-pass.png" alt="The trip card as a boarding pass: Home to Work, distance, energy, efficiency, and a 38p fare with £4.93 saved against petrol" width="360"></p>

## What you get

- **A receipt for every charge**: energy split into solar, home battery and grid, minute by minute; cost from your electricity price for each half hour (Octopus rate sensors work as they are); solar valued at the export price you gave up, or free; miles added and cost per mile.
- **A receipt for every drive over a mile**: distance, time, speeds, energy, efficiency, cost (from what charged the car), the share of sunshine in the battery, and the petrol comparison.
- **This month**: charging cost, solar share, miles, cost per mile, and money saved against petrol.
- **Events** `clockwatch_charge_finished` and `clockwatch_trip_finished` for your own automations, and a `clockwatch.history` action that returns recent receipts.

## The cards

Three cards come with the integration and load by themselves: find them in the dashboard's card picker as **Clockwatch charge**, **Clockwatch trip** and **Clockwatch month**. The charge and trip cards have four styles each; choose one in the card's editor. The arrows at the bottom step back through older receipts.

### Charge

| Charging curve (default) | Classic |
| --- | --- |
| <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/charge-curve.png" alt="Charging curve style" width="360"> | <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/charge-classic.png" alt="Classic style: a teal card with the energy, a source bar and three tiles" width="360"> |
| **Pump display** | **Minimal** |
| <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/charge-pump.png" alt="Pump display style: a dark fuel-pump screen with sale, kWh and per-mile figures" width="360"> | <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/charge-minimal.png" alt="Minimal style: one line, a thin source bar and chips" width="360"> |

### Trip

| Boarding pass (default) | Till roll |
| --- | --- |
| <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/trip-pass.png" alt="Boarding pass style" width="360"> | <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/trip-tillroll.png" alt="Till roll style: a printed receipt with a sunshine stamp and the petrol comparison" width="360"> |
| **Route strip** | **Scorecard** |
| <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/trip-strip.png" alt="Route strip style: from and to on a line, chips and the cost against petrol" width="360"> | <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/trip-score.png" alt="Scorecard style: an efficiency ring, the trip against your average, and a badge for the month's best trips" width="360"> |

### Month

<img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/month.png" alt="The month card: miles, charging cost, cost per mile, solar share, weekly charging by source, and the saving against petrol" width="360">

They follow your Home Assistant theme, light or dark:

<img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/charge-curve-dark.png" alt="Charging curve style in a dark theme" width="360"> <img src="https://raw.githubusercontent.com/SinghTejveer/clockwatch/main/docs/trip-pass-dark.png" alt="Boarding pass style in a dark theme" width="360">

```yaml
type: custom:clockwatch-trip-card
style: pass        # pass, tillroll, strip or score; the charge card has curve, classic, pump or minimal
units: mi          # optional: mi or km; Home Assistant's own setting when left out
entity: sensor.clockwatch_model_3_last_trip   # optional: only needed with more than one car
```

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

Everything is worked out and stored in your Home Assistant, and nothing is sent anywhere. If you choose the car's location sensor, a trip keeps only the names of the zones it started and ended in ("Home", "Work", or "Away"), never coordinates.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

To work on the cards, serve the repository (`python -m http.server`) and open `/dev/cards.html`: every style with sample receipts. Add `?dark`, `?metric`, `?empty`, or `?only=trip-score` for one card.

## Licence

MIT
