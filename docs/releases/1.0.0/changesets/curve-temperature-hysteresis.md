---
"pifanctl": minor
"pifanctl-chart": minor
"pifanctl-operator": minor
---

Feature(control): Temperature hysteresis for fan curves

The fan now starts at the curve's start temperature but only stops once the temperature has fallen a hysteresis below its peak, 5 °C by default, matching the official Raspberry Pi 5 fan. This keeps a fan whose own cooling pulls the temperature back under the start point from switching on and off over and over. Set `--temp-hysteresis`, the chart value `curve.hysteresis` or the Fan field `temperatureHysteresis` to change it, or to 0 to restore the previous behaviour.
