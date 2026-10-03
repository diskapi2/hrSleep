# hrSleep

Sleep aid web app.

- **hrSleep/** — sleep aid web app. Plays soothing MIDI music whose tempo follows your live
  heart rate (from a Bluetooth HR device) minus an offset X, gently encouraging the heart to slow.
  Live at https://diskapi2.github.io/hrSleep/hrSleep/ (Chrome, Web Bluetooth).
  Local test: `cd hrSleep && python -m http.server 8000`, then open http://localhost:8000.
  Regenerate music: `python hrSleep/genMidi.py --bpm 60 --seed 7 --out hrSleep/music`.

See CLAUDE.md for details.
