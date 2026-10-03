# Project: hrSleep

Repo: github.com/diskapi2/hrSleep (this repo contains only hrSleep).

## Repo layout
- hrSleep/ — sleep aid web app: music whose tempo follows the user's heart rate.
  - index.html: single-file web app (no build step), plus sw.js (service worker). It is published on GitHub Pages at
    https://diskapi2.github.io/hrSleep/hrSleep/ and used in Chrome on a Pixel 8 Pro.
  - music/*.mid + music/manifest.json: generated MIDI pieces, steady 60 bpm,
    quarter note = 1 beat, loopable (canon_ground 4/4, slow_waltz 3/4, pentatonic_drift 4/4,
    moonlight 4/4, brahms_lullaby 3/4).
  - genMidi.py: generates the MIDI files with no dependencies (has its own SMF writer and a
    minimal Humdrum **kern reader). Args: --bpm, --seed, --out. It rewrites manifest.json,
    which index.html reads. Existing files regenerate byte-identically (seed = --seed + index),
    so append new pieces at the end of PIECES.
  - scores/*.krn: public-domain pieces in Humdrum **kern format, read by genMidi.py.
    moonlight_1.krn = Beethoven Sonata no. 14 mvt 1, from github.com/craigsapp/beethoven-piano-sonatas
    (same repo has all 32 sonatas). Cut time is written as 4/4 so one beat = one triplet
    group; the score's tempo is quarter = 108, so at heart rate it plays at about half speed.

## hrSleep concept
Play soothing music. Read live heart rate from a Bluetooth device (Fitbit Charge 6 via its
heart rate sharing during an exercise session, or a chest strap), then set the music tempo to
(smoothed HR − X) bpm so the heart is gently encouraged to slow down toward sleep.
Example: X = 5, HR 70 → music at 65 bpm.

## How index.html works
- Heart rate input: Web Bluetooth, standard Heart Rate service 0x180D / heart_rate_measurement.
  Parses 8/16-bit HR and RR intervals (1/1024 s units), reads battery_service if present.
  Connecting (keepConnected/connectOnce): every step (gatt.connect, service/characteristic
  discovery, startNotifications) has a 10 s timeout — on Android gatt.connect() can hang
  forever — with a 0.6 s pause after connect, retries with backoff, one loop at a time
  (bleSession cancels, bleBusy marks a running loop), and a single shared notification
  listener so reconnects never double the readings. A watchdog in the 1 Hz loop resets a
  link that is up but silent for 30 s; gattserverdisconnected then reconnects.
  Pixel 8 Pro + Charge 6 (from the in-app event log): the link is already up (Fitbit app),
  connect takes 10–60 ms, and startNotifications() either succeeds in < 0.5 s or never
  answers / fails with NotSupportedError; retrying on the same link only queues behind the
  stuck request, and a fresh connection is what succeeds. So: one startNotifications per
  connection with a 6 s timeout (BLE_NOTIFY_MS), then disconnect and retry after 1.5 s
  (5 s after 15 attempts). A reading that arrives without the promise resolving counts as
  success. Choosing the same device again disconnects it and waits 1.5 s before connecting
  (an immediate connect got cut by the pending disconnect).
  testing without a device.
- Control loop, once per second: EMA-smoothed HR (tau, default 20 s) → target = clamp(HR − X,
  min 45, max 90) → tempo glides toward the target, limited to 6 bpm/min. If no HR arrives for
  10 s (STALE_MS), the tempo is held. If Play is pressed before any HR, the tempo jumps to the
  first target.
- Audio: Tone.js 14.8.49 + @tonejs/midi 2.0.28 from jsDelivr. The app replaces Tone's context
  with one using latencyHint "playback" and lookAhead 0.5 s (against stalls/crackles on the
  phone). Tone.Transport / Tone.Draw / Tone.context stay bound to the discarded original
  context, so the code uses `Transport` / `Draw` (from Tone.getTransport()/getDraw()) and
  Tone.getContext() — never the Tone.* aliases. MIDI is scheduled in ticks
  (Transport.PPQ = file PPQ), so changing Transport.bpm retimes playback with no pitch
  artifacts. Piano/harp tracks use the Salamander piano Sampler (falls back to a synth when
  offline); strings/pad General MIDI programs (40–55, 88–95) use a soft PolySynth. Reverb on all.
- UI: dark night theme, readouts (HR / smoothed / music bpm), canvas chart, settings sliders
  saved in localStorage (defaults in DEFAULTS), screen Wake Lock while playing, "Dim" black
  overlay (double-tap to exit), fade-out timer.
- Offline cache: sw.js precaches index.html, music/* (from manifest.json), the two CDN
  libraries and the 18 Salamander samples. Own files are network-first (3 s timeout, then
  cache), so pushed updates still arrive; CDN/samples are cache-first. Bump CACHE in sw.js
  only to force a full re-download (e.g. after changing the sample list).
- Event/error log ("Show error log" button): logEvent() keeps the last 500 entries in
  localStorage (hrSleep.events) — every BLE step with timing, failures, disconnects, watchdog
  resets, window errors/unhandled rejections and console.warn/error. Copy button for sending.
- Log: 1 row/s, kept in localStorage in chunks of 300 rows (keys hrSleep.log.0..n-1 and
  hrSleep.log.chunks; only unsaved chunks are rewritten, every 30 s and on pagehide; an old
  single-key hrSleep.log is migrated on load). The chart draws only when visible, binary-
  searches the start row and decimates to ~2 points per pixel. Downloadable as CSV with columns
  time, elapsed_s, hr_bpm, rr_ms, hr_smooth, target_bpm, music_bpm, source, piece, offset_x.

## Constraints
- The user's local machine runs Python 3.7 (Anaconda, pandas 0.25, no plotly). Keep Python
  code 3.7-compatible (no walrus operator, no `list[int]` style annotations, etc.).
- Web Bluetooth only works over https or localhost, so the phone uses the GitHub Pages
  address. Local testing: run `python -m http.server 8000` in hrSleep/.
- Bluetooth cannot be tested in a cloud or headless session. Verify logic with Simulate mode.

## Status / open items
- Verified with the simulator: tempo follows HR (measured playback rate matches the set bpm),
  piece switching, dim mode, CSV log, layout at phone width.
- Verified on the phone: Bluetooth connection to the Charge 6 (heart rate sharing during an
  exercise session) works, and is reliable since the timeout/retry rewrite.
- Not yet verified: the chest strap.
- Possible next steps: an hrSleep analysis script (does HR follow the music? reads the app's
  CSV log), more or longer MIDI pieces, and a stepped tempo mode.
