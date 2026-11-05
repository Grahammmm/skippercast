# Runbook: Morro Bay AIS receiver (parts, site, install, licence note, rollback)

**Owner:** repository owner (purchase, signups, host consent). An agent writes the PRs and reads the heartbeat; it buys nothing and contacts no host.
**Related:** [fleet AIS listener down](fleet-ais-down.md) (the listener this feeds).

## 1. Purpose and status

aisstream has no reception between 34.5°N and 36.5°N, which covers Morro Bay, Estero Bay and Port San Luis (AIS-LIVE plan, cause 1). A small receive-only station near Morro Bay would let the fleet listener hear boats there.

Status: **plan only. Nothing has been bought.** The purchase is G's call (AISLIVE-07) and happens **only if AISLIVE-02 finds a local boat transmitting**. This runbook orders nothing and contacts no one.

Rules that do not change: the watch gate and `decide()` in `match.py` stay as they are; robots rules and WAFs are never bypassed; we never claim to watch a boat we have not heard; anything public carries counts only (no MMSI, no position, no personal name).

## 2. Parts

Prices are the figures in `reports/AIS-LIVE-PLAN.md` (route B), except power, which the plan does not price. **Price not re-checked** against the vendor pages on any date: the builder of this runbook had no web access, so every figure below is the plan's, not a live quote. The plan gives no power-supply price, so none is shown. Re-check each on the buy date and write that date in the "Date checked" column before anything is bought.

| Part | Option | Price (USD) | Date checked | Link |
|---|---|---|---|---|
| Receiver | 1: dAISy HAT (AIS receiver on a Pi HAT) | 79 (EUR 65 at openmarine) | price not re-checked | https://www.wegmatt.com/ , https://www.openmarine.net/ |
| Computer | Raspberry Pi, with SD card | 80 (plan range 60-80) | price not re-checked | https://www.raspberrypi.com/products/ |
| Antenna | Marine VHF antenna | 100 (plan range 50-150) | price not re-checked | vendor choice at buy time |
| Cable and mount | coax, connector, mast clamp | 40 | price not re-checked | vendor choice at buy time |
| Power | Pi power supply and outdoor-rated plug | unknown: not in the plan, no dated quote yet | not checked | https://www.raspberrypi.com/products/27w-power-supply/ (official Pi supply page, 2026-11-05: lists resellers, no price shown) |
| Receiver | 2 (alternative): RTL-SDR dongle plus AIS-catcher software, replaces the dAISy HAT | no figure in the plan | price not re-checked | https://www.rtl-sdr.com/ |

**Total, option 1:** the four plan-priced parts are 79 + 80 + 100 + 40 = **$299**. Power is **unknown** until a dated, linked vendor price is written in the table, so the complete total is unknown and is not claimed to be under the $350 limit. Under $350 holds only if the power quote is $51 or less and the other parts stay at the plan figures. The antenna is the swing item: at the plan's top figure ($150) the four parts alone are $349, leaving $1 for power, so re-check every price and take the question back to G before buying if the complete total reaches $350.

## 3. Site criteria

- **Antenna height:** as high as is safe; the plan's range figure is about 15-20 nautical miles from 15 m, more from a ridge.
- **Line of sight:** clear view to the Morro Bay harbour mouth and out over Estero Bay. Hills, buildings and trees between the antenna and the water cut range sharply.
- **Port San Luis may need its own site.** Terrain can hide the inner waters from a Morro Bay site, so do not promise Port San Luis coverage from this one.
- **Power:** mains power at the mast or a short run to it.
- **Network:** wired Ethernet or Wi-Fi; outbound connections only, no inbound port opened.
- **Physical security and consent:** a spot out of casual reach, with the host's consent.
- **Records:** write only a site class (for example "rooftop, harbour side") on the card. No street address anywhere in the repo or a card.

## 4. Licence note

The receiver only listens and never transmits. The project's reading is that no FCC station licence is therefore needed. This is **the project's reading, not legal advice**; the owner confirms it before relying on it.

## 5. Install

Nothing here is run by an agent, and nothing here restarts the live listener.

1. Mount and connect the antenna through the cable to the receiver (dAISy HAT on the Pi, or the RTL-SDR dongle). Power the Pi.
2. Option 1: read the dAISy HAT's serial output and forward the NMEA sentences over UDP or TCP on the local network. Option 2: run AIS-catcher and have it send NMEA to a UDP or TCP port.
3. The listener reads that stream through `SKIPPERCAST_AIS_NMEA_URL` and the `ais.sources` list (AISLIVE-03 and AISLIVE-04, which define the source named `local-nmea`). If those units merged under other names, use the merged names.
4. Turning the source on is a **region-config change made by a PR**, never a hand edit on the runner. After it merges, restart through the existing install path in [fleet AIS listener down](fleet-ais-down.md) (`fleet-ais-listener.yml` dispatch), not by hand.

## 6. Drop own-ship sentences

Own-ship reports are `AIVDO` sentences (our own vessel, not other traffic). The listener's NMEA adapter drops `AIVDO` lines. Also set the receiver not to emit them where its settings allow that. A receiver with no transmitter has no own ship, so any `AIVDO` line is noise at best.

## 7. Optional feeds

Sharing the stream with AISHub or Open Waters is **optional and a G signup**: G decides whether to join and creates the account; no agent signs up or sends data. Caveat: AISHub's terms do not allow redistributing the raw feed, so nothing from it is republished here, and only counts appear in anything public.

## 8. Check it works

Counts only, no MMSI or position:

- `jq '.sources["local-nmea"] | {connected, messages}' ~/.local/share/skippercast/fleet/CA/ais/heartbeat.json` shows `connected: true` and a messages count that rises between heartbeats (written every 60 s). The key names follow AISLIVE-04's heartbeat as merged.
- Once AISLIVE-01 has merged, its per-port coverage block in the fleet report names Morro Bay as heard.

If the count stays at 0, the usual causes are antenna, cable or line of sight, not software. A boat we have not heard is never shown as watched.

## 9. Rollback

1. Remove `local-nmea` from `ais.sources` in the region config, by PR.
2. Restart through the existing install path ([fleet AIS listener down](fleet-ais-down.md)).
3. Power the receiver off and disconnect it.

The listener then runs on aisstream alone. No data is lost: the raw store keeps what was already written.
