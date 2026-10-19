# Live passive verification on R1

Date: 2026-10-19, evening (CST). No RF was transmitted and nothing was injected
into the hub. The USRP uplink was captured passively with an AF_PACKET socket
while the station carried normal user traffic.

## What was captured

| Capture | Feature | Window | Complete transmissions |
|---|---|---|---|
| capture-off.bin | `SquelchTailElim=0` | 20:17:39 - 20:20:20 | 7 |
| capture-on-early.bin | `SquelchTailElim=1`, 200 ms | 20:04 - 20:17 | 4 |
| capture-on.bin | `SquelchTailElim=1`, 200 ms | 20:22 - 20:25 | 3 |

Each analysis file next to the captures contains the per transmission metrics.

## Measurements

| Metric | OFF (n=7) | ON (n=7, both windows) |
|---|---|---|
| last 100 ms RMS | 0.156 - 0.179, **mean 0.164** | 4 of 7 below 0.02, 3 of 7 0.11 - 0.17 |
| transmissions ending loud | **7 / 7** | 3 / 7 |
| terminal loud segment | 180 - 700 ms, **mean 363 ms** | 0 - 1220 ms, mean 340 ms |

Pitch periodicity of the final 100 ms versus mid-speech (normalised
autocorrelation peak, 66-400 Hz search):

| | final 100 ms | mid speech |
|---|---|---|
| OFF | 0.13 - 0.41, mean **0.26** | 0.39 - 0.73, mean **0.59** |

The last 100 ms of an unmodified transmission is significantly less periodic
than the speech in the middle of the same transmission, which is what a
squelch tail (broadband receiver noise) looks like. The real tail on this
repeater is long: the loud end segment measured 180 - 700 ms, mean 363 ms.

## Interpretation

* With the feature off every captured transmission ends with a loud,
  non periodic segment right up to the USRP PTT-off packet. That is the
  squelch tail being delivered to the hub.
* With the feature on and a 200 ms delay, 4 of 7 transmissions end in silence
  instead, which is exactly what the delay line produces: the last 200 ms of
  received audio is dropped and the stream stops earlier.
* The remaining 3 loud endings are consistent with real tails longer than
  200 ms. A 200 ms delay can only remove 200 ms of tail; the measured tail
  length (mean 363 ms) suggests that 300 - 400 ms would remove noticeably more,
  at the cost of cutting more speech when the tail happens to be short.

## Limitations, stated honestly

* The two windows carried different transmissions from different users, there
  is no controlled reference signal, and the sample is small (7 + 7).
* The real tail length is not under our control, so this is passive
  observation, not a controlled RF tail test.
* Conclusion: **offline verification is complete and passed; real RF tail
  elimination is partially verified.** A controlled RF test (a known noise
  burst of 50 / 100 / 200 / 500 ms injected at the receiver) would be needed
  for full verification, and that requires access to the RF side.
