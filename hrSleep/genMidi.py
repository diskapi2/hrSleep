#!/usr/bin/env python
"""Generate soothing, loopable MIDI pieces with a steady beat at a known tempo.

Every piece is written at --bpm (default 60) with one quarter note per beat,
so a player can retime it to (heart rate - X) by scaling the tempo.

Usage:
    python genMidi.py                 # writes music/*.mid at 60 bpm
    python genMidi.py --bpm 60 --seed 7 --out music
"""
import argparse
import json
import os
import random
import re
import struct
from fractions import Fraction

PPQ = 480  # ticks per quarter note (= one beat)


# ----------------------------------------------------------------------------
# Minimal Standard MIDI File (type 1) writer -- no external dependencies
# ----------------------------------------------------------------------------
def vlq(n):
    """Encode an int as a MIDI variable-length quantity."""
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


class Track(object):
    def __init__(self, name, channel=0, program=0, volume=100):
        self.name = name
        self.channel = channel
        self.program = program
        self.volume = volume
        self.notes = []  # (start_beat, dur_beats, pitch, velocity)

    def note(self, start, dur, pitch, vel):
        self.notes.append((start, dur, pitch, vel))


def track_chunk(events, end_tick):
    """events: list of (tick, order, bytes). order sorts note-offs before note-ons."""
    data = b""
    last = 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        data += vlq(tick - last) + msg
        last = tick
    data += vlq(max(0, end_tick - last)) + b"\xFF\x2F\x00"  # end of track
    return b"MTrk" + struct.pack(">I", len(data)) + data


def meta_text(kind, text):
    raw = text.encode("ascii", "replace")
    return b"\xFF" + bytes([kind]) + vlq(len(raw)) + raw


def write_midi(path, title, bpm, beats_per_bar, total_beats, tracks):
    end_tick = int(round(total_beats * PPQ))
    us_per_beat = int(round(60000000.0 / bpm))
    conductor = [
        (0, 0, meta_text(0x03, title)),
        (0, 0, b"\xFF\x51\x03" + us_per_beat.to_bytes(3, "big")),
        (0, 0, b"\xFF\x58\x04" + bytes([beats_per_bar, 2, 24, 8])),
    ]
    chunks = [track_chunk(conductor, end_tick)]

    for tr in tracks:
        ch = tr.channel
        ev = [
            (0, 0, meta_text(0x03, tr.name)),
            (0, 0, bytes([0xC0 | ch, tr.program])),
            (0, 0, bytes([0xB0 | ch, 7, tr.volume])),
        ]
        # next start of the same pitch, so overlapping repeats are cut short
        starts = {}
        for start, _, pitch, _ in tr.notes:
            starts.setdefault(pitch, []).append(int(round(start * PPQ)))
        for start, dur, pitch, vel in tr.notes:
            on = int(round(start * PPQ))
            later = [s for s in starts[pitch] if s > on]
            off = min([end_tick, int(round((start + dur) * PPQ))] + later)
            if off <= on:
                continue
            ev.append((on, 2, bytes([0x90 | ch, pitch, max(1, min(127, vel))])))
            ev.append((off, 1, bytes([0x80 | ch, pitch, 0])))
        chunks.append(track_chunk(ev, end_tick))

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), PPQ)
    with open(path, "wb") as f:
        f.write(header + b"".join(chunks))


# ----------------------------------------------------------------------------
# Minimal Humdrum **kern reader (for public-domain scores in scores/)
# ----------------------------------------------------------------------------
KERN_STEP = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def kern_pitch(tok):
    """MIDI pitch of a kern note token: c = C4 (60), cc = C5, C = C3, CC = C2."""
    m = re.search(r"([A-Ga-g])\1*", tok)
    letters = m.group(0)
    octave = 3 + len(letters) if letters[0].islower() else 4 - len(letters)
    pitch = 12 * (octave + 1) + KERN_STEP[letters[0].lower()]
    for ch in tok[m.end():]:
        if ch == "#":
            pitch += 1
        elif ch == "-":
            pitch -= 1
        else:
            break
    return pitch


def kern_dur(tok):
    """Duration in quarter-note beats: 4 = quarter, 12 = triplet eighth, dots add halves."""
    m = re.search(r"(\d+)(\.*)", tok)
    d = add = Fraction(4, int(m.group(1)))
    for _ in m.group(2):
        add /= 2
        d += add
    return d


def read_kern(path):
    """Return (notes, total_beats) from a **kern file.

    notes: (start, dur, pitch, spine) with times in beats as Fractions; spine is the
    original column (0 = first **kern spine). Ties are merged; rests, grace notes and
    non-kern spines (e.g. **dynam) are skipped. Handles spine splits (*^) and merges (*v).
    """
    spines, ends, kinds = [], [], []   # per current column: source spine, end time
    notes, ties = [], {}
    t = Fraction(0)
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\r\n") for ln in f]
    for ln in lines:
        if not ln or ln.startswith("!") or ln.startswith("="):
            continue
        cols = ln.split("\t")
        if ln.startswith("**"):
            kinds = cols
            spines = list(range(len(cols)))
            ends = [t] * len(cols)
            continue
        if ln.startswith("*"):
            new_sp, new_end, i = [], [], 0
            while i < len(cols):
                if cols[i] == "*^":
                    new_sp += [spines[i]] * 2
                    new_end += [ends[i]] * 2
                    i += 1
                elif cols[i] == "*v":
                    j = i
                    while j < len(cols) and cols[j] == "*v":
                        j += 1
                    new_sp.append(spines[i])
                    new_end.append(max(ends[i:j]))
                    i = j
                else:
                    new_sp.append(spines[i])
                    new_end.append(ends[i])
                    i += 1
            spines, ends = new_sp, new_end
            continue
        music = [k for k in range(len(cols)) if kinds[spines[k]] == "**kern"]
        if all(cols[k] == "." for k in music):
            continue  # e.g. a dynamics-only line: no time passes
        for k in music:
            if cols[k] == ".":
                continue
            sp = spines[k]
            for tok in cols[k].split(" "):
                if "q" in tok or not re.search(r"\d", tok):
                    continue  # grace note or null
                d = kern_dur(tok)
                ends[k] = t + d
                if "r" in tok:
                    continue
                p = kern_pitch(tok)
                if ("]" in tok or "_" in tok) and (sp, p) in ties:
                    i = ties[(sp, p)]
                    s0, d0, _, _ = notes[i]
                    notes[i] = (s0, d0 + d, p, sp)
                    if "]" in tok:
                        del ties[(sp, p)]
                    continue
                notes.append((t, d, p, sp))
                if "[" in tok:
                    ties[(sp, p)] = len(notes) - 1
        t = min(ends[k] for k in music if ends[k] > t)
    return notes, t


# ----------------------------------------------------------------------------
# Pieces (original arrangements unless noted; quarter note = one beat)
# ----------------------------------------------------------------------------
def human(rng, vel, spread=4):
    return vel + rng.randint(-spread, spread)


def piece_canon(rng):
    """Canon-style ground bass (public-domain progression), 4/4, 32 bars."""
    # (bass pitch, chord root pitch class, minor?)
    prog = [(50, 2, False), (45, 9, False), (47, 11, True), (42, 6, True),
            (43, 7, False), (38, 2, False), (43, 7, False), (45, 9, False)]
    whole_mel = [78, 76, 74, 73, 71, 69, 71, 73]
    half_mel = [(78, 74), (76, 73), (74, 71), (73, 69), (71, 67), (69, 66), (71, 67), (73, 76)]

    bass = Track("Cello", channel=0, program=42, volume=85)
    arp = Track("Piano", channel=1, program=0, volume=100)
    mel = Track("Strings", channel=2, program=49, volume=80)

    passes = 4
    for p in range(passes):
        for i, (b, root, minor) in enumerate(prog):
            bar = p * len(prog) + i
            t = bar * 4
            bass.note(t, 4, b, human(rng, 48, 3))
            base = 55 + (root - 55) % 12          # chord root in G3..F#4
            third = 3 if minor else 4
            for k, iv in enumerate([0, 7, third + 12, 7]):
                arp.note(t + k, 1.5, base + iv, human(rng, 56 if k == 0 else 48))
            if p == 1:
                mel.note(t, 4, whole_mel[i], human(rng, 50, 3))
            elif p == 2:
                a, c = half_mel[i]
                mel.note(t, 2, a, human(rng, 52, 3))
                mel.note(t + 2, 2, c, human(rng, 48, 3))
    return dict(title="Canon Ground", beats_per_bar=4, total_beats=passes * 8 * 4,
                tracks=[bass, arp, mel])


def piece_gymno(rng):
    """Slow 3/4 waltz alternating Gmaj7 / Dmaj7 with a wandering melody, 36 bars."""
    chords = [(43, [59, 62, 66]), (38, [57, 61, 66])]   # Gmaj7, Dmaj7
    chord_tones = [{67, 71, 74, 78}, {66, 69, 73, 74, 78}]
    scale = [66, 67, 69, 71, 73, 74, 76, 78, 79]          # D major, F#4..G5

    lh = Track("Piano LH", channel=0, program=0, volume=95)
    rh = Track("Piano RH", channel=1, program=0, volume=100)

    bars = 36
    for bar in range(bars):
        t = bar * 3
        b, ch = chords[bar % 2]
        lh.note(t, 3, b, human(rng, 50, 3))
        for n in ch:
            lh.note(t + 1, 2, n, human(rng, 40, 3))

    # Melody: 4 phrases of 8 bars after a 4-bar intro.
    idx = 5
    for ph in range(4):
        start_bar = 4 + ph * 8
        bar = start_bar
        while bar < start_bar + 6:
            choices = [[3], [2, 1], [1, 1, 1]]
            if bar < start_bar + 5:  # a two-bar pattern must not run into the cadence
                choices.append([3, 3])
            pattern = rng.choice(choices)
            t = bar * 3
            for k, d in enumerate(pattern):
                if k == 0:  # land on a chord tone at the downbeat
                    tones = [i for i, n in enumerate(scale) if n in chord_tones[(t // 3) % 2]]
                    idx = min(tones, key=lambda i: abs(i - idx))
                else:
                    idx = max(0, min(len(scale) - 1, idx + rng.choice([-1, -1, 1, 2, -2])))
                rh.note(t, d, scale[idx], human(rng, 58 if k == 0 else 50))
                t += d
            bar += 2 if sum(pattern) == 6 else 1
        # cadence: long note on a chord tone, then a bar of rest
        cad_bar = start_bar + 6
        tones = [i for i, n in enumerate(scale) if n in chord_tones[cad_bar % 2]]
        idx = min(tones, key=lambda i: abs(i - 2))
        rh.note(cad_bar * 3, 5, scale[idx], human(rng, 52))
    return dict(title="Slow Waltz", beats_per_bar=3, total_beats=bars * 3, tracks=[lh, rh])


def piece_pentatonic(rng):
    """Warm pad with a soft harp note on every beat (C pentatonic), 4/4, 32 bars."""
    prog = [(48, [60, 64, 67]), (45, [57, 60, 64]), (41, [57, 60, 65]), (43, [59, 62, 67])]
    penta = [60, 62, 64, 67, 69, 72, 74, 76, 79, 81]

    pad = Track("Pad", channel=0, program=89, volume=75)
    harp = Track("Harp", channel=1, program=46, volume=100)

    bars = 32
    idx = 4
    for bar in range(bars):
        t = bar * 4
        b, ch = prog[(bar // 2) % len(prog)]
        if bar % 2 == 0:
            pad.note(t, 8, b, human(rng, 42, 2))
            for n in ch:
                pad.note(t, 8, n, human(rng, 36, 2))
        for k in range(4):
            if k == 0:
                pcs = {n % 12 for n in ch}
                tones = [i for i, n in enumerate(penta) if n % 12 in pcs]
                idx = min(tones, key=lambda i: abs(i - idx))
            else:
                idx = max(0, min(len(penta) - 1, idx + rng.choice([-2, -1, -1, 1, 1, 2])))
            harp.note(t + k, 2, penta[idx], human(rng, 54 if k == 0 else 44))
    return dict(title="Pentatonic Drift", beats_per_bar=4, total_beats=bars * 4, tracks=[pad, harp])


def piece_moonlight(rng):
    """Beethoven, Piano Sonata no. 14 'Moonlight', 1st movement (public domain), 69 bars.

    Notes come from scores/moonlight_1.krn (Craig Stuart Sapp's Humdrum edition after
    the Durand 1915 edition). Cut time is written as 4/4 here so that one beat is one
    group of triplets; the score's tempo (half = 54) is quarter = 108, so playing it at
    heart rate is about half speed. Damper pedal is approximated by letting the triplets
    ring for one beat.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    notes, total = read_kern(os.path.join(here, "scores", "moonlight_1.krn"))
    third = Fraction(1, 3)

    bass = Track("Piano LH", channel=0, program=0, volume=95)
    arp = Track("Piano triplets", channel=1, program=0, volume=90)
    mel = Track("Piano melody", channel=2, program=0, volume=105)

    melody_at = {(s, p) for s, d, p, sp in notes if d != third}
    for start, dur, pitch, spine in notes:
        if dur == third:
            if (start, pitch) in melody_at:
                continue  # melody note doubles the triplet: strike it once
            arp.note(float(start), 1.0, pitch, human(rng, 36, 3))
        elif spine == 1 or dur < 1:   # right hand, or dotted melody in the left hand
            mel.note(float(start), float(dur), pitch, human(rng, 58, 3))
        else:
            bass.note(float(start), float(dur), pitch, human(rng, 46, 3))
    return dict(title="Moonlight Sonata", beats_per_bar=4, total_beats=int(total),
                tracks=[bass, arp, mel])


def piece_brahms(rng):
    """Brahms, Wiegenlied op. 49 no. 4 (public domain), 3/4 in F major, 4 verses + intro.

    A gentle arrangement for babies: rocking waltz accompaniment (bass, then two soft
    chords), melody on the piano; verse 2 adds a music-box octave above and a soft pad,
    verse 4 is the quietest.
    """
    # melody per bar as (pitch, beats); the two pickup eighths (A4 A4) end the bar before
    mel_bars = [
        [(72, 1.5), (69, .5), (69, 1)],         # Lul-la-by and good
        [(72, 2), (69, .5), (72, .5)],          # night, with ro-
        [(77, 1), (76, 1.5), (74, .5)],         # ses be-dight, with
        [(74, 1), (72, 1), (67, .5), (69, .5)],
        [(70, 1), (67, 1), (67, .5), (69, .5)],
        [(70, 2), (67, .5), (70, .5)],
        [(76, .5), (74, .5), (72, 1), (76, 1)],
        [(77, 2), (65, .5), (65, .5)],
        [(77, 2), (74, .5), (70, .5)],
        [(72, 2), (69, .5), (65, .5)],
        [(70, 1), (72, 1), (74, 1)],
        [(72, 2), (65, .5), (65, .5)],
        [(77, 2), (74, .5), (70, .5)],
        [(72, 2), (69, .5), (65, .5)],
        [(70, 1), (69, 1), (67, 1)],
        [(65, 2)],                              # + pickup into the next verse
    ]
    pickup = [(69, .5), (69, .5)]
    F, C7, Bb = (41, [53, 57, 60]), (48, [52, 55, 58]), (46, [53, 58, 62])
    harmony = [F, F, C7, C7, C7, C7, C7, F, Bb, F, Bb, F, Bb, F, C7, F]

    lh = Track("Piano LH", channel=0, program=0, volume=85)
    rh = Track("Piano melody", channel=1, program=0, volume=100)
    box = Track("Music box", channel=2, program=0, volume=70)
    pad = Track("Pad", channel=3, program=89, volume=60)

    def accomp(bar, chord, soft):
        t = bar * 3
        bass, tones = chord
        lh.note(t, 3, bass, human(rng, 44 - soft, 2))
        for beat in (1, 2):
            for n in tones:
                lh.note(t + beat, 1, n, human(rng, 30 - soft, 2))

    def melody(t, notes, soft, octave_box):
        for pitch, d in notes:
            rh.note(t, d, pitch, human(rng, 56 - soft, 3))
            if octave_box:
                box.note(t, d, pitch + 12, human(rng, 34, 2))
            t += d

    verses = 4
    accomp(0, F, 0)                             # intro bar, ends with the pickup
    melody(2, pickup, 0, False)
    for v in range(verses):
        soft = 8 if v == verses - 1 else 0
        for i, notes in enumerate(mel_bars):
            bar = 1 + v * 16 + i
            accomp(bar, harmony[i], soft)
            melody(bar * 3, notes, soft, v == 1)
            if v in (1, 2) and i % 2 == 0:      # pad holds each two-bar harmony
                bass, tones = harmony[i]
                for n in tones:
                    pad.note(bar * 3, 6 if harmony[i + 1] == harmony[i] else 3, n, human(rng, 32, 2))
                if harmony[i + 1] != harmony[i]:
                    for n in harmony[i + 1][1]:
                        pad.note(bar * 3 + 3, 3, n, human(rng, 32, 2))
            if i == 15 and v < verses - 1:
                melody(bar * 3 + 2, pickup, soft, v == 1)
    bars = 1 + verses * 16
    return dict(title="Brahms Lullaby", beats_per_bar=3, total_beats=bars * 3,
                tracks=[lh, rh, box, pad])


PIECES = {
    "canon_ground": piece_canon,
    "slow_waltz": piece_gymno,
    "pentatonic_drift": piece_pentatonic,
    "moonlight": piece_moonlight,
    "brahms_lullaby": piece_brahms,
}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Generate loopable MIDI pieces at a fixed tempo.")
    ap.add_argument("--bpm", type=float, default=60.0, help="native tempo (default 60)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for melodies")
    ap.add_argument("--out", default=os.path.join(here, "music"), help="output folder")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for i, (name, fn) in enumerate(PIECES.items()):
        p = fn(random.Random(args.seed + i))
        path = os.path.join(args.out, name + ".mid")
        write_midi(path, p["title"], args.bpm, p["beats_per_bar"], p["total_beats"], p["tracks"])
        secs = p["total_beats"] * 60.0 / args.bpm
        manifest.append(dict(file=name + ".mid", title=p["title"], bpm=args.bpm,
                             beats_per_bar=p["beats_per_bar"], beats=p["total_beats"]))
        print("%-22s %-18s %d/4  %3d beats  %4.0f s @ %g bpm" % (
            name + ".mid", p["title"], p["beats_per_bar"], p["total_beats"], secs, args.bpm))

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("Wrote %d pieces + manifest.json to %s" % (len(manifest), args.out))


if __name__ == "__main__":
    main()
