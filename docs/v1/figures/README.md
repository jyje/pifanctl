# Cooling systems manual figures

Static exports of the conversation's systems-manual schematic: physical side
view, configuration and temperature paths, and automatic control sequence.
Each of the four states is rendered for shared rack fans and per-board fans,
with English and Korean labels. Every PNG has a corresponding editable SVG.

- `normal`: complete data, temperature curve controls the assigned fan.
- `hot`: pi-03 rises to 78°C; only the fan assigned to that member reaches 100%.
- `missing`: pi-03 has no sample; its assigned fan enters failsafe at 100%.
- `watchdog`: operator heartbeat has expired; affected workers request 100%.

Values are illustrative, not measurements. The figures show steady-state target
duty and omit the downward ramp. Full power loss cannot guarantee fan operation.

Regenerate from the repository root:

```sh
# Requires librsvg's rsvg-convert and a font with Korean glyphs.
python3 scripts/render_cooling_manual.py
```

The script writes the SVG first, then converts it to a 1920 × 1880 PNG.
Fan glyph: [Lucide fan](https://lucide.dev/icons/fan),
[ISC license](https://github.com/lucide-icons/lucide/blob/main/LICENSE).
The surrounding schematic and text are authored for pifanctl.
