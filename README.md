# WLED → LIFX LAN bridge (DDP)

Drive LIFX bulbs — including a 21-bulb, 3-tier chandelier of LIFX Candle matrix bulbs — from
[WLED](https://kno.wled.ge/) (or any [DDP](http://www.3waylabs.com/ddp/) source) in real time,
using the [LIFX LAN protocol](https://lan.developer.lifx.com/docs/introduction). The bridge runs
as a single Node-RED tab with no extra palettes.

```
WLED (ESP32) ──DDP/UDP 4048──▶ Node-RED "DDP → LIFX LAN" ──LIFX LAN/UDP 56700──▶ bulbs
   effects, presets,              decode frame, map pixels → bulbs,
   segments per tier              rate-limit, render candle modes,
        ▲                         find bulbs by MAC, arbitrate power
        │
 Home Assistant (WLED integration: segment lights + preset select)
```

## Pixel map (WLED bus "DDP RGB → 192.168.2.143", 25 px at WLED index 200–224)

| DDP px | WLED px | What |
|---|---|---|
| 0–2 | 200–202 | Swag lamp (bottom, middle, top) |
| 3–5 | 203–205 | Chandelier tier 1 (top), positions 1–3 |
| 6–11 | 206–211 | Chandelier tier 2 (middle), positions 1–6 |
| 12–23 | 212–223 | Chandelier tier 3 (bottom), positions 1–12 |
| 24 | 224 | **Mode control** (WLED segment "Flame mode") |

Positions run **counter-clockwise viewed from above** on every tier (verified with
`chandelier_test.py rainbow`).

## Modes (chosen by the control pixel)

| Control pixel | Mode | What the candles do |
|---|---|---|
| black / segment off | **solid** | one colour per candle (`SetColor`), ≤20 msgs/s per bulb |
| blue-dominant | **starfield** | candle = WLED colour as background; random 1–3 zones flash white with random offsets |
| any other colour | **flame** | base→tip gradient (dim/saturated base, bright/lighter tip) + flicker across the 5×6 zones |

Matrix modes use `Set64` (one message paints a whole candle) and share a **hard cap of 250
messages/s** (`matrixBudget`). See *Airtime* below — don't raise it casually.

## WLED presets

| # | Name | |
|---|---|---|
| 10 | Chandelier tiers | Colorwaves per tier, solid mode |
| 11 | Chandelier whole | one segment across all 21 candles (effects spiral top→bottom) |
| 12 | Chandelier flame | Candle Multi, warm orange, flame mode |
| 13 | Chandelier starfield | dark blue sky, starfield mode |

## Arbitration with Home Assistant

If a group (lamp / tier 1 / tier 2 / tier 3) receives only black for 4 s (e.g. its WLED segment
is turned off), the bridge **powers those bulbs off and releases them**, so HA's own LIFX entities
work without being overwritten. Colour again → bridge powers them on and takes over. Power
commands are sent ×3 and re-asserted every 10 s while streaming (UDP has no acks).

HA entities: `light.wled_chandelier_top|middle|bottom`, `light.wled_swag_lamp`,
`light.wled_chandelier_flame_mode`, `select.wled_preset`; per-bulb `light.tierXbulbY`.

## Airtime (read this before adding effects)

On 2026-11-23, ~300+ `Set64` msgs/s for several minutes wedged the 2.4 GHz radio of an
Omada EAP787 (fw 1.5.6) — every 2.4 GHz client went dark until the AP was rebooted.
Measured: starfield at ~267 msgs/s raised 2.4 GHz utilisation 22% → 32% and recovered;
"rising streak" sparkles (~310–340 msgs/s) preceded the failure and were dropped.
Keep `matrixBudget` ≤ 250 and send from the wired Node-RED host.

## Files

| File | Purpose |
|---|---|
| `build_flow.py` | Generates `flows/ddp-lifx-lan.json` (the Node-RED tab) from `chandelier_bulbs.json` |
| `deploy.sh` | Generate → syntax-check → back up → `PUT /flow/<tab>` on Node-RED |
| `chandelier_bulbs.json` | **Source of truth**, keyed by MAC: name, tier, position, LIFX target, IP, matrix size |
| `lifx_inventory.py` | Scan a /24 for LIFX, match to inventory, `--write` fills IP/product/fw/matrix |
| `restore_labels.py` | Put bulb labels back from the inventory (`--apply`) |
| `onboard_all.py` | Re-onboard bulbs stuck in setup mode (see below) |
| `chandelier_test.py` | Position test patterns: `rainbow`, `flash <name>`, `warm` |
| `ddp_test_sender.py` | DDP test source (solid / rainbow / chase / breathe) |
| `ha_ws.py` | Tiny stdlib Home Assistant WebSocket client (registry edits) |
| `omada.py` | Tiny read-only Omada controller client (AP/radio stats) |
| `sparkle.py`, `spiral.py` | Direct-to-bulb effect prototypes (spiral didn't look good; kept for reference) |
| `wled/` | WLED `cfg.json` / `presets.json` snapshot (Wi-Fi SSID redacted; WLED exports password lengths only) |

## When the chandelier bulbs drop off Wi-Fi

They occasionally fall back to setup mode (they advertise `LIFX Candle Color xxxxxx` APs).
From WSL on the Windows PC (built-in adapter "Wi-Fi"; Windows *Location* access must be on):

```bash
python3 -W ignore onboard_all.py --list      # see who's in setup mode
python3 -W ignore onboard_all.py             # rejoin all (creds from ~/homeassistant/wifi.txt)
python3 lifx_inventory.py --write            # refresh IPs
python3 restore_labels.py --apply            # restore names
```

The setup-AP suffix is the bulb's LIFX target (Wi-Fi MAC − 1), so bulbs are identified before
onboarding. Onboarding packet format from
[tserong/lifx-hacks `onboard.py`](https://github.com/tserong/lifx-hacks/blob/master/onboard.py).
The bridge finds bulbs by MAC every 30 s, so IP changes don't need a redeploy.

## Hardware notes

- LIFX Candle Colour: 5×6 matrix — 5 columns around the candle (rows 1–5) + 1 tip zone (row 0).
  Product 137 (fw 3.91); Tier1Bulb3 is product 68 (fw 3.90).
- WLED 16.0.1 on an ESP32 (LEDeez-style board), 200 px WS281x strip on GPIO 4 plus the DDP bus.
- Future: Inovelli Zigbee switch in Smart Bulb mode (relay always on), button taps → WLED presets.
