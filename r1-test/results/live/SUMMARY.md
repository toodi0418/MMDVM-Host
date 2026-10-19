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

## Statistical comparison

Last 100 ms RMS of every analysed transmission:

```
OFF: 0.1555 0.1621 0.1612 0.1584 0.1653 0.1660 0.1786   median 0.1621
ON : 0.1538 0.1662 0.0083 0.0108 0.0087 0.0102 0.1126   median 0.0108
```

Loud endings (last 100 ms RMS >= 0.05): OFF 7/7, ON 3/7.

* Fisher exact, one sided: **p = 0.0350**
* Mann-Whitney U = 43.0, z = 2.36 (two sided p ~ 0.018)

The split is significant at the five percent level even with seven
transmissions per arm. Caveat: the two arms carried different traffic at
different times, so this stays an observational comparison and not a
controlled experiment.

## Verification of the deployed artefact

The full offline suite was also run against the binary that is actually
installed on R1, from a copy of the scripts in /tmp so that nothing on the
running system is modified:

```
MMDVM_MODIFIED=/usr/local/bin/MMDVMHost \
MMDVM_BASELINE=/tmp/r1-verify/baseline/MMDVMHost python3 run_tests.py
=> TOTAL: 15/15 PASS
```

The tested artefact, the deployed binary and the stored copy in
/usr/local/etc/r1-tail-elim all have SHA256
caf4b2e40ca6f9b638c65722760bd9ce3e4a6b7c26ed440e765fad60343cdbfe.

