# FocusPen

A closed-loop haptic attention aid. This repo has four parts that run
independently but talk to each other over MQTT:

```
firmware/   PlatformIO project for the Seeed XIAO ESP32-S3 (the pen)
broker/     Mosquitto config — the message bus everything else uses
backend/    FastAPI service: windowing, classification, guard layer,
            session recording, the WebSocket the dashboard listens on
frontend/   React dashboard — live graphs, windowing strip, controls
```

Data flow: **pen → MQTT → backend → MQTT → pen**, with the dashboard
watching the backend over a WebSocket and sending control commands
over REST. The pen and the dashboard never talk to each other directly.

---

## Run order

Start these in order — each one depends on the previous being up.

### 1. Broker

```bash
cd broker
mosquitto_passwd -c passwordfile pen01       # prompts for a password
mosquitto_passwd   passwordfile backend
mosquitto_passwd   passwordfile controller
mosquitto -c mosquitto.conf -v
```

Leave this running in its own terminal. The `-v` flag prints every
connect/subscribe/publish, which is the fastest way to confirm the
pen and backend are actually talking once you wire them up.

Match the passwords you just set to `firmware/include/config.h`
(`MQTT_PASS`) and `backend/app/mqtt_client.py` (`MQTT_PASS`).

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

If you don't have a trained TCN yet, comment `torch` out of
`requirements.txt` — the rule-based model (`classifier.py: RuleModel`)
runs the whole pipeline with zero trained weights, so you can test
everything else first.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite prints a `Network:` URL (not just `Local:`) — that's the one a
phone on the same WiFi can open. The backend's CORS is wide open for
now (`allow_origins=["*"]`), which is fine on your own LAN and not
fine anywhere else.

### 4. Firmware

Edit `firmware/include/config.h` first:
- `WIFI_SSID` / `WIFI_PASSWORD`
- `MQTT_HOST` — your PC's LAN IP (`ipconfig` / `ifconfig`), never `localhost`
- `MQTT_USER` / `MQTT_PASS` — must match what you set in step 1
- `DEVICE_ID` — unique per pen if you build more than one

```bash
cd firmware
pio run                  # compile
pio run -t upload        # flash
pio device monitor -b 115200   # watch it boot and connect
```

You should see, in order: sensor init, WiFi connecting, MQTT
connecting, then a steady stream of nothing on serial (data is going
out over MQTT, not serial) while the broker terminal shows incoming
publishes on `focuspen/pen01/data`.

---

## Wiring reference

| Signal | XIAO pin | Goes to |
|---|---|---|
| I2C SDA | D4 (GPIO5) | MPU-6050 SDA **and** DRV2605L SDA (shared bus) |
| I2C SCL | D5 (GPIO6) | MPU-6050 SCL **and** DRV2605L SCL |
| FSR signal | D0 (GPIO1, ADC) | node between FSR and a 10kΩ pulldown to GND |
| 3V3 / GND | — | both sensor boards, FSR top leg, a 100µF cap across the rail near the DRV2605L |
| LRA | — | DRV2605L OUT+/OUT− only — **never** wired to the XIAO directly |

The 100µF cap matters: the LRA's current burst can sag the rail enough
to glitch an I2C read if it's missing.

---

## What "handle all scenarios" means in this firmware

- **WiFi drops mid-session** → `maintainWiFi()` retries every 5s,
  non-blocking. Sampling continues the whole time; samples queue
  locally (see below).
- **Broker drops / restarts** → `maintainMQTT()` retries every 3s. The
  pen's LWT (`focuspen/<id>/status` = `offline`) fires automatically
  on the broker side the moment the TCP connection dies, so the
  dashboard's online/offline indicator updates with no polling.
- **Publish can't keep up** → batches queue in a bounded ring
  (`MAX_BATCH_QUEUE`, default 10 × ~200ms = ~2s of buffer). If the
  queue fills during an extended outage, the *oldest* batch is
  dropped to make room for new ones — recent data is judged more
  useful than very stale data for a live attention aid. This is a
  known, documented limitation: there's no SD card fallback in this
  version, so a disconnect longer than ~2s loses data. Worth adding
  if you need bulletproof session recording later.
- **A sensor isn't found at boot** (bad wiring, cold solder joint) →
  the pen doesn't halt. `sensorsReady` / `hapticReady` flags track
  each independently; `initSensors()` retries every 2s in `loop()`.
  If only the DRV2605L is missing, the pen still streams data — it
  just can't buzz until that's fixed.
- **A bad haptic/config payload arrives** → JSON parsing failures are
  caught and logged over serial; malformed messages are dropped, not
  crashed on.

---

## Dev mode — how it's actually enforced

The dashboard's dev-mode toggle calls `POST /api/devmode` with a
password (`FOCUSPEN_DEV_PASSWORD` env var on the backend, default
`focuspen-dev` — **change this**). Every state-changing endpoint
(`/api/config`, `/api/trigger`, `/api/models/*`, `/api/session/*`)
checks `state.dev_mode` server-side before doing anything. A second
layer sits at the broker itself: `broker/acl.conf` means only the
`backend` MQTT user can publish to any pen's `haptic` or `config`
topic — a browser can't bypass dev-mode by talking to MQTT directly
even if it tried, because browsers never hold MQTT credentials at all
in this architecture.

---

## Known gaps / next steps

- No on-device inference yet — `focuspen/<id>/inference` is wired up
  and handled on the backend side, but nothing publishes to it until
  you get a model running on the ESP32 itself.
- Backend assumes one broker on `localhost`; change `MQTT_HOST` in
  `backend/app/mqtt_client.py` if the broker runs elsewhere.
- No TLS anywhere — fine on a closed LAN during development, not fine
  if this ever leaves your bench.
- `DEV_MODE_PASSWORD` and the MQTT passwords are placeholders —
  rotate them before any demo where people you don't fully trust are
  on the same WiFi.
