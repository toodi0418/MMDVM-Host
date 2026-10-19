#!/usr/bin/env python3
"""Automated PASS/FAIL test suite for the R1 FM squelch tail elimination."""

import json
import math
import os
import random
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mmdvm_harness as H
import mmdvm_dsp as D

REPO = os.path.dirname(HERE)
BASE = os.path.dirname(REPO)
MODIFIED = os.environ.get("MMDVM_MODIFIED", os.path.join(REPO, "MMDVMHost"))
BASELINE = os.environ.get("MMDVM_BASELINE", os.path.join(BASE, "baseline", "MMDVMHost"))
WORK = os.path.join(HERE, "work")
RESULTS = os.path.join(HERE, "results")

SAMPLE_RATE = 8000

INI = """[General]
Callsign=TEST
Id=1234567
Timeout=180
Duplex=0
RFModeHang=10
NetModeHang=3
Display=
Daemon=0

[Log]
DisplayLevel=1
FileLevel=0
FilePath=
FileRoot=MMDVM

[Info]
RXFrequency=439000000
TXFrequency=439000000
Power=1
Latitude=0.0
Longitude=0.0
Height=0
Location=Test
Description=Test
URL=

[Modem]
Protocol=udp
ModemAddress=127.0.0.1
ModemPort={modem_port}
LocalAddress=127.0.0.1
LocalPort={modem_local_port}
UARTPort=
UARTSpeed=115200
RXInvert=0
TXInvert=0
PTTInvert=0
TXDelay=100
DMRDelay=0
RXLevel=50
CWIdTXLevel=50
DStarTXLevel=50
DMRTXLevel=50
YSFTXLevel=50
P25TXLevel=50
NXDNTXLevel=50
M17TXLevel=50
POCSAGTXLevel=50
FMTXLevel=50
AX25TXLevel=50

[D-Star]
Enable=0

[DMR]
Enable=0

[System Fusion]
Enable=0

[P25]
Enable=0

[NXDN]
Enable=0

[POCSAG]
Enable=0

[M17]
Enable=0

[AX 25]
Enable=0

[FM]
Enable=1
Callsign=TEST
ModeHang=10

[FM Network]
Enable=1
Protocol=USRP
SampleRate=8000
LocalAddress=127.0.0.1
LocalPort={local_port}
GatewayAddress=127.0.0.1
GatewayPort={gateway_port}
PreEmphasis=1
DeEmphasis=1
TXAudioGain=1.0
RXAudioGain=1.0
ModeHang=3
Debug=0
{tail_keys}

[Lock File]
Enable=0

[Remote Control]
Enable=0
"""


def ensure_writable():
    """Pi-Star remounts the root filesystem read only every hour at :17."""
    probe = os.path.join(WORK, ".write_probe")
    try:
        os.makedirs(WORK, exist_ok=True)
        with open(probe, "w") as handle:
            handle.write("x")
        os.remove(probe)
        return True
    except OSError:
        pass
    os.system("sudo mount -o remount,rw / >/dev/null 2>&1")
    try:
        with open(probe, "w") as handle:
            handle.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def speech(seconds, freqs=(400.0, 800.0, 1600.0), amp=0.45, seed=1):
    n = int(seconds * SAMPLE_RATE)
    out = []
    for i in range(n):
        t = float(i) / SAMPLE_RATE
        value = 0.0
        for k, f in enumerate(freqs):
            value += math.sin(2.0 * math.pi * f * t + k) / (k + 1)
        value = (value / 3.0) * amp
        value *= 0.6 + 0.4 * math.sin(2.0 * math.pi * 2.5 * t)
        out.append(value)
    fade = int(0.005 * SAMPLE_RATE)
    for i in range(min(fade, n)):
        out[i] *= float(i) / fade
    return out


def noise(ms, amp=0.25, seed=7):
    rnd = random.Random(seed)
    n = int(ms * SAMPLE_RATE / 1000.0)
    return [rnd.uniform(-amp, amp) for _ in range(n)]


def silence(ms):
    return [0.0] * int(ms * SAMPLE_RATE / 1000.0)


def write_ini(path, modem_port, modem_local_port, local_port, gateway_port,
              tail_elim, tail_ms):
    tail_keys = "SquelchTailElim=%d" % tail_elim + chr(10) + "SquelchTailElimMs=%s" % tail_ms
    text = INI.format(modem_port=modem_port, modem_local_port=modem_local_port,
                      local_port=local_port, gateway_port=gateway_port,
                      tail_keys=tail_keys)
    with open(path, "w") as handle:
        handle.write(text)


def start_transmission(binary, tail_elim, tail_ms, label, extra_sleep=0.0):
    ensure_writable()
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)

    used = set()
    ports = []
    while len(ports) < 4:
        port = free_udp_port()
        if port in used:
            continue
        used.add(port)
        ports.append(port)
    modem_port, modem_local_port, local_port, gateway_port = ports

    modem = H.ModemEmulator(modem_port, modem_local_port)
    modem.start()

    ini_path = os.path.join(WORK, label + ".ini")
    write_ini(ini_path, modem_port, modem_local_port, local_port, gateway_port,
              tail_elim, tail_ms)

    capture = H.UsrpCapture(gateway_port)
    capture.start()

    runner = H.HostRunner(binary, ini_path, WORK)
    runner.start()

    ok = modem.version_seen.wait(12.0)
    if not ok:
        runner.stop()
        modem.close()
        capture.close()
        raise RuntimeError("no version handshake for " + label)

    if not runner.wait_for_log("FM Network Parameters", 12.0):
        runner.stop()
        modem.close()
        capture.close()
        raise RuntimeError("FM network did not open for " + label)

    if extra_sleep:
        time.sleep(extra_sleep)

    return {
        "modem": modem,
        "capture": capture,
        "runner": runner,
        "local_port": local_port,
        "gateway_port": gateway_port,
        "ini": ini_path,
    }


def finish_transmission(ctx, wait_end=True):
    modem = ctx["modem"]
    capture = ctx["capture"]
    runner = ctx["runner"]

    if wait_end:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if any(H.is_end(data) for (_, data) in capture.snapshot()):
                break
            time.sleep(0.02)

    time.sleep(0.25)

    packets = capture.snapshot()
    log = runner.log_text()
    rss = runner.rss_kb()

    runner.stop()
    modem.close()
    capture.close()

    return {"packets": packets, "log": log, "rss": rss,
            "rx_frames": list(modem.rx_frames)}


def analyse(packets):
    audio = H.decode_audio(packets)
    infos = [H.parse_usrp(data) for (_, data) in packets]
    infos = [i for i in infos if i is not None]

    seqs = [i["seq"] for i in infos if i["type"] == 0]
    audio_packets = [i for i in infos if i["type"] == 0 and i["ptt"] == 1]
    starts = [i for i in infos if i["type"] == 2]
    ends = [i for i in infos if i["type"] == 0 and i["ptt"] == 0]

    # Group packets per transmission, the USRP sequence restarts at every start
    groups = []
    current = None
    for (ts, data) in packets:
        info = H.parse_usrp(data)
        if info is None:
            continue
        if info["type"] == 2:
            current = {"seqs": [], "stamps": []}
            groups.append(current)
        elif info["type"] == 0:
            if current is None:
                current = {"seqs": [], "stamps": []}
                groups.append(current)
            current["seqs"].append(info["seq"])
            if H.is_audio(data):
                current["stamps"].append(ts)

    intervals = []
    for group in groups:
        for index in range(1, len(group["stamps"])):
            intervals.append((group["stamps"][index] - group["stamps"][index - 1]) * 1000.0)

    group_ok = True
    for group in groups:
        seqs_g = group["seqs"]
        for index in range(1, len(seqs_g)):
            if seqs_g[index] != seqs_g[index - 1] + 1:
                group_ok = False

    return {
        "audio": audio,
        "audio_samples": len(audio),
        "payload_sizes": sorted(set(len(i["payload"]) for i in audio_packets)),
        "packet_count": len(audio_packets),
        "start_count": len(starts),
        "end_count": len(ends),
        "seqs": seqs,
        "groups": groups,
        "group_ok": group_ok,
        "intervals": intervals,
    }


def expected_output(frames, tail_elim, tail_ms, deemphasis=True):
    filtered = D.host_filter(frames, deemphasis=deemphasis)
    if not tail_elim:
        return filtered
    delay = int(tail_ms * SAMPLE_RATE / 1000.0)
    if delay <= 0:
        return filtered
    body = filtered[:max(0, len(filtered) - delay)]
    return [0.0] * delay + body


def compare(output, expected):
    n = min(len(output), len(expected))
    if n == 0:
        return 0.0
    return D.correlation(output[:n], expected[:n])


def settle_wait(capture, min_packets=1, timeout=3.0):
    last = -1
    stable = time.monotonic()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        packets = capture.snapshot()
        count = sum(1 for (_, d) in packets if H.is_audio(d))
        if count == last and count >= min_packets:
            if time.monotonic() - stable > 0.25:
                break
        else:
            last = count
            stable = time.monotonic()
        time.sleep(0.02)
    return capture.snapshot()


def quantise(frames):
    out = []
    for x in frames:
        v = int(round(x * 2047.0))
        if v > 2047:
            v = 2047
        if v < -2048:
            v = -2048
        out.append(v / 2048.0)
    return out


def expected_stream(bursts, tail_elim, tail_ms):
    concat = []
    for burst in bursts:
        concat.extend(burst)
    filtered = D.host_filter(quantise(concat))
    if not tail_elim:
        return filtered
    delay = int(tail_ms * SAMPLE_RATE / 1000.0)
    if delay <= 0:
        return filtered
    out = []
    pos = 0
    for burst in bursts:
        out.extend([0.0] * delay)
        piece = filtered[pos:pos + len(burst)]
        out.extend(piece[:max(0, len(piece) - delay)])
        pos += len(burst)
    return out


def evaluate(name, result, bursts, tail_elim, tail_ms, extra=None, opts=None):
    metrics = analyse(result["packets"])
    output = metrics["audio"]
    expected = expected_stream(bursts, tail_elim, tail_ms)
    expected_alt = expected_stream(bursts, not tail_elim, tail_ms)

    corr = compare(output, expected)
    corr_alt = compare(output, expected_alt)

    delay = int(tail_ms * SAMPLE_RATE / 1000.0) if tail_elim else 0
    # Measure the delay of every burst against the undelayed reference. The
    # expected waveform already has the delay and the chop built in, so it is
    # not usable for the delay measurement itself.
    reference = expected_stream(bursts, 0, tail_ms)
    max_lag = max(20, int(tail_ms / 20.0) + 15) if tail_elim else 20
    lag_frames = 0.0
    lag_ok = True
    lag_detail = []
    pos = 0
    for burst in bursts:
        ref_seg = reference[pos:pos + len(burst)]
        out_seg = output[pos:pos + len(burst)]
        lag, score = D.best_lag(D.frame_rms(ref_seg), D.frame_rms(out_seg), max_lag)
        lag_detail.append("%.1f fr (r=%.3f)" % (lag, score))
        if pos == 0:
            lag_frames = lag
        expected_lag = delay / float(H.FRAME_SAMPLES)
        if abs(lag - expected_lag) > 1.5:
            lag_ok = False
        pos += len(burst)

    total_input = sum(len(b) for b in bursts)
    intervals = metrics["intervals"]
    seqs = metrics["seqs"]
    seq_ok = all(seqs[i + 1] == seqs[i] + 1 for i in range(len(seqs) - 1))

    opts = opts or {}
    expected_starts = opts.get("expected_starts", len(bursts))
    max_gap_ms = opts.get("max_gap_ms", 120.0)

    checks = []
    def check(label, ok, detail):
        checks.append({"check": label, "pass": bool(ok), "detail": detail})

    check("waveform matches expected", corr >= 0.97,
          "corr=%.4f (alt hypothesis %.4f)" % (corr, corr_alt))
    check("expected hypothesis is the closer one", corr > corr_alt,
          "corr=%.4f vs alt=%.4f" % (corr, corr_alt))

    expected_lag = delay / float(H.FRAME_SAMPLES)
    check("delay matches configured value", lag_ok,
          "configured %.0f ms, measured %s" % (tail_ms if tail_elim else 0.0,
                                              ", ".join(lag_detail)))
    check("stream length matches", abs(len(output) - total_input) <= 2 * H.FRAME_SAMPLES,
          "output=%d input=%d samples" % (len(output), total_input))

    check("USRP start packet count matches transmissions",
          metrics["start_count"] == expected_starts,
          "start=%d expected=%d bursts=%d" % (metrics["start_count"],
                                              expected_starts, len(bursts)))
    check("USRP end packet sent", metrics["end_count"] >= 1,
          "end packets=%d" % metrics["end_count"])
    check("USRP sequence contiguous inside each transmission", metrics["group_ok"],
          "transmissions=%d packets=%d" % (len(metrics["groups"]), len(seqs)))
    if intervals:
        ordered = sorted(intervals)
        median = ordered[len(ordered) // 2]
        worst = max(intervals)
        # The median is used instead of the mean so that a deliberately long gap
        # (the lost EOT case) does not push the statistic out of range.
        check("packet cadence", median <= 25.0 and worst <= max_gap_ms,
              "median=%.1fms max=%.1fms (limit %.0f)" % (median, worst, max_gap_ms))
    else:
        check("packet cadence", False, "no intervals")
    check("payload size is 320 bytes", metrics["payload_sizes"] == [320],
          "sizes=%s" % metrics["payload_sizes"])
    check("no delay line failure logged", "delay line failed" not in result["log"],
          "log length=%d" % len(result["log"]))

    if extra:
        for (label, ok, detail) in extra:
            check(label, ok, detail)

    passed = all(c["pass"] for c in checks)
    return {
        "name": name,
        "pass": passed,
        "checks": checks,
        "metrics": {
            "output_samples": len(output),
            "input_samples": total_input,
            "packets": metrics["packet_count"],
            "start": metrics["start_count"],
            "end": metrics["end_count"],
            "corr": corr,
            "corr_alt": corr_alt,
            "delay_frames": lag_frames,
            "delay_ms": lag_frames * 20.0,
            "rss_kb": result["rss"],
        },
        "log_tail": result["log"][-600:],
        "log_full": result["log"],
    }


def run_bursts(binary, tail_elim, tail_ms, bursts, label, eot_delay_ms=0.0,
               send_eot=None, gap_ms=0):
    if send_eot is None:
        send_eot = [True] * len(bursts)
    ctx = start_transmission(binary, tail_elim, tail_ms, label)
    modem = ctx["modem"]
    for index, burst in enumerate(bursts):
        if gap_ms and index > 0:
            time.sleep(gap_ms / 1000.0)
        H.stream_audio(modem, burst)
        if send_eot[index]:
            if eot_delay_ms:
                time.sleep(eot_delay_ms / 1000.0)
            modem.send_fm_eot()
    result = finish_transmission(ctx)
    return result


def usrp_downlink_packet(seq, samples):
    import struct
    header = (b"USRP" + struct.pack(">I", seq) + b"\x00" * 4 +
              struct.pack(">I", 1) + b"\x00" * 4 +
              struct.pack(">I", 0) + b"\x00" * 8)
    body = bytearray()
    for value in samples:
        raw = int(round(value * 32767.0))
        if raw > 32767:
            raw = 32767
        if raw < -32768:
            raw = -32768
        body.append(raw & 0xFF)
        body.append((raw >> 8) & 0xFF)
    return header + bytes(body)


def case_downlink(binary, tail_elim, tail_ms, label):
    ctx = start_transmission(binary, tail_elim, tail_ms, label)
    modem = ctx["modem"]
    capture = ctx["capture"]

    # Enter FM mode with a very short RF burst
    H.stream_audio(modem, speech(0.2))
    modem.send_fm_eot()
    time.sleep(0.3)

    before = len(modem.frames_of(H.CMD_FM_DATA))

    # Push network audio (downlink) into the host
    tone = speech(1.0, freqs=(600.0,))
    seq = 0
    for index in range(0, len(tone), H.FRAME_SAMPLES):
        chunk = tone[index:index + H.FRAME_SAMPLES]
        packet = usrp_downlink_packet(seq, chunk)
        capture.sock.sendto(packet, ("127.0.0.1", ctx["local_port"]))
        seq += 1
        time.sleep(0.02)

    time.sleep(0.5)

    frames = modem.frames_of(H.CMD_FM_DATA)
    payloads = [payload for (_, payload) in frames][before:]

    result = finish_transmission(ctx, wait_end=False)
    result["downlink_payloads"] = payloads
    return result


def case_invalid_config(tail_ms_value, expect_ms, label):
    ctx = start_transmission(MODIFIED, 1, tail_ms_value, label)
    modem = ctx["modem"]
    H.stream_audio(modem, speech(0.2))
    modem.send_fm_eot()
    result = finish_transmission(ctx)
    log = result["log"]
    checks = []
    checks.append({"check": "warning logged for invalid value",
                   "pass": "SquelchTailElimMs=" in log,
                   "detail": [line for line in log.split("\n") if "SquelchTailElimMs" in line][:2]})
    checks.append({"check": "effective value clamped and logged",
                   "pass": ("Squelch Tail Elim Delay: %dms" % expect_ms) in log,
                   "detail": "expect %dms" % expect_ms})
    passed = all(c["pass"] for c in checks)
    return {"name": label, "pass": passed, "checks": checks,
            "metrics": {"rss_kb": result["rss"]},
            "log_tail": log[-800:], "log_full": log}


def run_suite(selected=None):
    results = []

    # 1. Compatibility: disabled must behave exactly like the baseline binary
    frames = speech(1.5) + noise(100)
    res_mod = run_bursts(MODIFIED, 0, 200, [frames], "compat_modified_off")
    res_base = run_bursts(BASELINE, 0, 200, [frames], "compat_baseline_off")
    mod_eval = evaluate("compat_modified_off", res_mod, [frames], 0, 200)
    base_eval = evaluate("compat_baseline_off", res_base, [frames], 0, 200)
    out_mod = analyse(res_mod["packets"])["audio"]
    out_base = analyse(res_base["packets"])["audio"]
    n = min(len(out_mod), len(out_base))
    cross = D.correlation(out_mod[:n], out_base[:n]) if n else 0.0
    compat_ok = (mod_eval["pass"] and base_eval["pass"] and cross >= 0.99 and
                 abs(len(out_mod) - len(out_base)) <= 2 * H.FRAME_SAMPLES)
    results.append({
        "name": "compat_disabled_vs_baseline",
        "pass": compat_ok,
        "checks": [
            {"check": "modified OFF matches expected upstream behaviour",
             "pass": mod_eval["pass"], "detail": "see compat_modified_off"},
            {"check": "baseline binary matches expected upstream behaviour",
             "pass": base_eval["pass"], "detail": "see compat_baseline_off"},
            {"check": "modified OFF output equals baseline output",
             "pass": cross >= 0.99 and abs(len(out_mod) - len(out_base)) <= 2 * H.FRAME_SAMPLES,
             "detail": "corr=%.5f len %d vs %d" % (cross, len(out_mod), len(out_base))},
        ],
        "metrics": {"corr": cross, "len_modified": len(out_mod), "len_baseline": len(out_base)},
    })

    # 2. Tail elimination matrix
    matrix = [
        ("tail_200ms_of_200_d200", 200, 200),
        ("tail_100ms_of_100_d100", 100, 100),
        ("tail_200ms_of_100_d200", 200, 100),
        ("tail_200ms_of_50_d200", 200, 50),
        ("tail_20ms_of_50_d20", 20, 50),
        ("tail_500ms_of_300_d500", 500, 300),
    ]
    for (name, delay_ms, tail_ms) in matrix:
        burst = speech(1.5) + noise(tail_ms)
        res = run_bursts(MODIFIED, 1, delay_ms, [burst], name)
        results.append(evaluate(name, res, [burst], 1, delay_ms))

    # 3. EOT arrives late (100 ms after the last audio frame)
    burst = speech(1.5) + noise(100)
    res = run_bursts(MODIFIED, 1, 200, [burst], "eot_delayed_100ms", eot_delay_ms=100.0)
    results.append(evaluate("eot_delayed_100ms", res, [burst], 1, 200))

    # 4. Rapid consecutive PTT with distinct tones
    bursts = [speech(0.4, freqs=(400.0,)),
              speech(0.4, freqs=(1000.0,)),
              speech(0.4, freqs=(1800.0,))]
    res = run_bursts(MODIFIED, 1, 200, bursts, "rapid_ptt", gap_ms=120)
    results.append(evaluate("rapid_ptt", res, bursts, 1, 200))

    # 5. Missing EOT, next transmission after a long gap
    b1 = speech(0.5, freqs=(500.0,))
    b2 = speech(0.5, freqs=(1500.0,))
    res = run_bursts(MODIFIED, 1, 200, [b1, b2], "no_eot_gap_reset",
                     send_eot=[False, True], gap_ms=600)
    # No EOT was sent, so the USRP transmission is never closed and the second
    # burst continues the same stream: one start packet and one long gap.
    results.append(evaluate("no_eot_gap_reset", res, [b1, b2], 1, 200,
                            opts={"expected_starts": 1, "max_gap_ms": 700.0}))

    # 6. Long transmission, memory growth
    long_frames = speech(20.0)
    ctx = start_transmission(MODIFIED, 1, 200, "long_run")
    modem = ctx["modem"]
    rss0 = ctx["runner"].rss_kb()
    H.stream_audio(modem, long_frames)
    modem.send_fm_eot()
    res = finish_transmission(ctx)
    rss1 = res["rss"]
    long_eval = evaluate("long_run", res, [long_frames], 1, 200)
    growth = (rss1 - rss0) if (rss0 is not None and rss1 is not None) else -1
    long_eval["checks"].append({"check": "no memory growth over 20 s transmission",
                                "pass": growth is not None and growth < 512,
                                "detail": "rss %s -> %s kB (delta %s)" % (rss0, rss1, growth)})
    long_eval["pass"] = all(c["pass"] for c in long_eval["checks"])
    long_eval["metrics"]["rss_delta_kb"] = growth
    results.append(long_eval)

    # 7. Invalid INI values
    results.append(case_invalid_config(5, 20, "invalid_low_5ms"))
    results.append(case_invalid_config(9999, 500, "invalid_high_9999ms"))
    results.append(case_invalid_config("abc", 20, "invalid_text_abc"))

    # 8. Downlink regression
    dl_on = case_downlink(MODIFIED, 1, 200, "downlink_on")
    dl_off = case_downlink(MODIFIED, 0, 200, "downlink_off")
    same = dl_on["downlink_payloads"] == dl_off["downlink_payloads"]
    results.append({
        "name": "downlink_unaffected",
        "pass": bool(dl_on["downlink_payloads"]) and same,
        "checks": [
            {"check": "downlink FM data was produced",
             "pass": bool(dl_on["downlink_payloads"]),
             "detail": "%d frames" % len(dl_on["downlink_payloads"])},
            {"check": "downlink bytes identical with tail elimination on and off",
             "pass": same,
             "detail": "on=%d off=%d frames" % (len(dl_on["downlink_payloads"]), len(dl_off["downlink_payloads"]))},
        ],
        "metrics": {"frames_on": len(dl_on["downlink_payloads"]),
                    "frames_off": len(dl_off["downlink_payloads"])},
    })

    return results


def main():
    ensure_writable()
    os.makedirs(RESULTS, exist_ok=True)
    started = time.time()
    results = run_suite()
    elapsed = time.time() - started

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = os.path.join(RESULTS, "results-%s.json" % stamp)
    with open(json_path, "w") as handle:
        json.dump(results, handle, indent=2)

    lines = []
    lines.append("MMDVMHost FM squelch tail elimination - automated test report")
    lines.append("Run: %s (%.1f s)" % (stamp, elapsed))
    lines.append("")
    lines.append("%-34s %s" % ("CASE", "RESULT"))
    for item in results:
        lines.append("%-34s %s" % (item["name"], "PASS" if item["pass"] else "FAIL"))
    lines.append("")
    lines.append("TOTAL: %d/%d PASS" % (passed, total))
    lines.append("")
    for item in results:
        lines.append("### %s : %s" % (item["name"], "PASS" if item["pass"] else "FAIL"))
        for check in item.get("checks", []):
            lines.append("  [%s] %s -- %s" % ("PASS" if check["pass"] else "FAIL",
                                              check["check"], check["detail"]))
        if item.get("metrics"):
            lines.append("  metrics: %s" % json.dumps(item["metrics"]))
        lines.append("")

    report = "\n".join(lines)
    md_path = os.path.join(RESULTS, "report-%s.md" % stamp)
    with open(md_path, "w") as handle:
        handle.write(report)

    print(report)
    print("json: %s" % json_path)
    print("md:   %s" % md_path)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
