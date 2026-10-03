# Project: hrSleep

Repo: github.com/diskapi2/hrSleep (this repo contains only hrSleep).

## Repo layout
- hrSleep/ — sleep aid web app: music whose tempo follows the user's heart rate.
  - index.html: single-file web app (no build step). It is published on GitHub Pages at
    https://diskapi2.github.io/hrSleep/hrSleep/ and used in Chrome on a Pixel 8 Pro.
  - music/*.mid + music/manifest.json: generated MIDI pieces, steady 60 bpm,
    quarter note = 1 beat, loopable (canon_ground 4/4, slow_waltz 3/4, pentatonic_drift 4/4).
  - genMidi.py: generates the MIDI files with no dependencies (has its own SMF writer).
    Args: --bpm, --seed, --out. It rewrites manifest.json, which index.html reads.

## hrSleep concept
Play soothing music. Read live heart rate from a Bluetooth device (Fitbit Charge 6 via its
heart rate sharing during an exercise session, or a chest strap), then set the music tempo to
(smoothed HR − X) bpm so the heart is gently encouraged to slow down toward sleep.
Example: X = 5, HR 70 → music at 65 bpm.

## How index.html works
- Heart rate input: Web Bluetooth, standard Heart Rate service 0x180D / heart_rate_measurement.
  Parses 8/16-bit HR and RR intervals (1/1024 s units), auto-reconnects, reads battery_service
  if present. A "Simulate" mode generates fake HR that drifts toward the music tempo, for
  testing without a device.
- Control loop, once per second: EMA-smoothed HR (tau, default 20 s) → target = clamp(HR − X,
  min 45, max 90) → tempo glides toward the target, limited to 6 bpm/min. If no HR arrives for
  10 s (STALE_MS), the tempo is held. If Play is pressed before any HR, the tempo jumps to the
  first target.
- Audio: Tone.js 14.8.49 + @tonejs/midi 2.0.28 from jsDelivr. MIDI is scheduled in ticks
  (Transport.PPQ = file PPQ), so changing Transport.bpm retimes playback with no pitch
  artifacts. Piano/harp tracks use the Salamander piano Sampler (falls back to a synth when
  offline); strings/pad General MIDI programs (40–55, 88–95) use a soft PolySynth. Reverb on all.
- UI: dark night theme, readouts (HR / smoothed / music bpm), canvas chart, settings sliders
  saved in localStorage (defaults in DEFAULTS), screen Wake Lock while playing, "Dim" black
  overlay (double-tap to exit), fade-out timer.
- Log: 1 row/s, kept in localStorage, downloadable as CSV with columns
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
- Not yet verified: a real Bluetooth connection to the Charge 6 (it may only share heart rate
  during an exercise session) or to the chest strap.
- Possible next steps: an hrSleep analysis script (does HR follow the music? reads the app's
  CSV log), more or longer MIDI pieces, and a stepped tempo mode.
