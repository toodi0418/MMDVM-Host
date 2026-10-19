# Automated test plan

The tests run the real MMDVMHost binary. Nothing is re-implemented except the
modem side of the MMDVM serial protocol.

## Test bed

```
run_tests.py
  |-- ModemEmulator      UDP modem port ([Modem] Protocol=udp)
  |     responds to GET_VERSION with protocol 2 and FM capability
  |     acknowledges SET_CONFIG, SET_FREQ and SET_FM_PARAMS1..4
  |     answers GET_STATUS so that the downlink FM space is non zero
  |     sends MMDVM FM_DATA frames (160 samples, 20 ms) and FM_EOT
  |-- UsrpCapture        UDP socket bound to the configured FM gateway port
  |     receives the USRP stream that MMDVMHost sends to the hub
  |-- HostRunner         runs <binary> <test.ini>, captures the log and VmRSS
```

Every case uses free ephemeral ports on 127.0.0.1, its own configuration file
and its own process. The production service and the production hub are never
involved.

## Stimulus

Speech is a deterministic three tone signal (400/800/1600 Hz, harmonic
weighting, 2.5 Hz amplitude modulation, 5 ms fade in). The squelch tail is
deterministic band limited white noise of a configurable length. Both are
generated in `run_tests.py` (`speech()` and `noise()`), no recording is needed,
so every run is bit for bit reproducible.

The audio is packed exactly like the firmware does it (12 bit offset binary,
two samples in three bytes).

## Analysis

`mmdvm_dsp.py` reproduces the MMDVMHost uplink DSP (de-emphasis plus the three
stage 300-2700 Hz filter) with the coefficients from `FMControl.cpp`, applied
to the quantised stimulus. The captured USRP audio is then compared with two
hypotheses:

* H0 (no elimination): `filtered(input)`
* H1 (elimination active): `D samples of silence + filtered(input)[:-D]`

Metrics per case:

* waveform correlation against H0 and H1
* measured delay per burst (Pearson correlation of the 20 ms RMS envelopes
  against the undelayed reference)
* output length versus input length
* USRP start packet count, end packet count, sequence continuity, packet
  interval statistics, payload size
* process VmRSS before and after the transmission
* log scan for warnings

## Cases

| Case | Purpose |
|---|---|
| `compat_disabled_vs_baseline` | `SquelchTailElim=0` on the modified binary versus the unmodified baseline binary: output must match both the expected upstream waveform and the baseline recording |
| `tail_200ms_of_200_d200` | Tail exactly covered by the delay: full removal, no speech loss |
| `tail_100ms_of_100_d100` | Smaller delay, exact match |
| `tail_200ms_of_100_d200` | Delay larger than the tail: 100 ms of speech truncated, quantified |
| `tail_200ms_of_50_d200` | Delay much larger than the tail: 150 ms of speech truncated, quantified |
| `tail_20ms_of_50_d20` | Minimum delay: only 20 ms of the 50 ms tail removed |
| `tail_500ms_of_300_d500` | Maximum delay |
| `eot_delayed_100ms` | EOT arrives 100 ms after the last audio frame |
| `rapid_ptt` | Three back to back transmissions, one start/end packet each, no audio leak between them |
| `no_eot_gap_reset` | EOT lost: the 300 ms gap detector must clear the delay line before the next transmission |
| `long_run` | 20 s continuous transmission: cadence, VmRSS growth |
| `invalid_low_5ms` | `SquelchTailElimMs=5` clamped to 20 with a warning |
| `invalid_high_9999ms` | `SquelchTailElimMs=9999` clamped to 500 with a warning |
| `invalid_text_abc` | non numeric value clamped to 20 with a warning |
| `downlink_unaffected` | USRP to RF downlink bytes identical with the feature on and off |

## PASS criteria

* waveform correlation with the expected hypothesis `>= 0.97`, and strictly
  better than the other hypothesis
* measured delay within 1.5 frames (30 ms) of the configured value
* output length within 2 frames of the input length
* expected number of USRP start packets (one per transmission that follows an EOT)
* at least one USRP end packet, one per closed transmission
* USRP sequence contiguous inside every transmission
* median packet interval `<= 25 ms`, worst interval `<= 120 ms` (700 ms for the
  lost EOT case where the stream intentionally stays open)
* every audio payload exactly 320 bytes (160 S16LE samples, 20 ms)
* no `delay line failed` warning in the log
* VmRSS growth below 512 kB over a 20 s transmission
* downlink FM data bytes identical with the feature on and off

A case passes only when all of its checks pass. The suite exits 0 only when
every case passes.

## Passive capture on the live repeater

`r1-test/capture_usrp.py` reads the USRP packets that the running MMDVMHost
sends to the hub with an AF_PACKET socket. It is completely passive: nothing is
transmitted, no packet is injected and the service is not restarted.

```bash
sudo python3 capture_usrp.py 900 /tmp/capture.bin eth0
python3 analyze_capture.py /tmp/capture.bin
```

`analyze_capture.py` splits the capture into transmissions (USRP start packet
to PTT off), decodes the audio and reports per transmission: duration, peak
RMS, the quiet tail length (the time between the last frame above 12 % of the
peak and the end of the stream), the RMS of the last 100 ms and its spectral
flatness (1.0 is noise like, low values are tonal speech).

Comparing the same station with the feature off and on gives an A/B on real
traffic without keying a transmitter and without injecting anything into the
hub. It is still not a controlled tail test: the length and content of the real
squelch tail is whatever the receiver produced, so the result is reported as
passive observation and not as a controlled RF verification.
