# Choosing SquelchTailElimMs for R1

The delay is a pure trade off: with a delay of `D` ms and a real squelch tail
of `T` ms measured from the end of the speech to the EOT reported by the modem,

* tail removed  = `min(T, D)`
* speech cut    = `max(0, D - T)`

This document records what the R1 receiver actually produces and what the
verified behaviour of the implementation is for tail lengths in that range.

## What the R1 receiver produces

Seven transmissions were captured passively with the feature disabled
(`r1-test/results/live/capture-off.bin`):

* the last 100 ms of every transmission is loud (RMS 0.156 - 0.179) and
  non periodic (normalised pitch autocorrelation 0.26, against 0.59 in the
  middle of the same speech), which is receiver noise and not speech;
* the loud, non periodic segment at the end measured **180 - 700 ms, mean
  363 ms**. A stricter voiced/unvoiced classifier isolated **160 - 340 ms** in
  the three transmissions where the speech to noise transition was clean.

Caveat: this is passive observation of different users at different times with
no controlled reference, so it bounds the tail length, it does not pin it down.

## Verified behaviour

`tail-length-matrix.txt` is the raw output. The deployed binary
(`/usr/local/bin/MMDVMHost`, SHA256 `caf4b2e4...`) was driven through the
automated harness with each combination:

| D (ms) | T (ms) | waveform correlation | measured delay | residual tail | speech cut | result |
|---|---|---|---|---|---|---|
| 200 | 350 | 1.000000 | 200 ms | 150 ms | 0 ms | PASS |
| 200 | 700 | 1.000000 | 200 ms | 500 ms | 0 ms | PASS |
| 400 | 350 | 1.000000 | 400 ms | 0 ms | 50 ms | PASS |
| 400 | 700 | 1.000000 | 400 ms | 300 ms | 0 ms | PASS |
| 200 | 180 | 1.000000 | 200 ms | 0 ms | 20 ms | PASS |
| 400 | 180 | 1.000000 | 400 ms | 0 ms | 220 ms | PASS |

The waveform correlation of 1.000000 means the output is exactly the delayed
input with the last `D` samples removed, so the two formulas above are the
measured behaviour and not an approximation.

## Recommendation

| Setting | Removes | Risk |
|---|---|---|
| `SquelchTailElimMs=200` (current) | the first 200 ms of tail | a residual tail remains whenever the real tail exceeds 200 ms, which the live data suggests is common on this receiver |
| `SquelchTailElimMs=300` - `400` | most of the observed range (up to 340 - 400 ms) | up to `D - T` ms of speech is cut when the tail happens to be short |
| `SquelchTailElimMs=500` (maximum) | everything the receiver produces | up to 500 ms of normal speech can be cut, only sensible if the tail really is that long |

The tail is produced by the receiver and the modem EOT timing, not by
MMDVMHost, so the correct way to choose the value is to measure it once on the
real hardware with a controlled carrier drop and set `D` to that measured tail
length. Until that measurement exists, 300 ms is a defensible middle ground:
it removes the tails observed up to 340 ms while cutting at most 300 ms of
speech in the worst case. Changing the value only needs an INI edit and a
service restart.
