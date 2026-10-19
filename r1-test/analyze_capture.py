#!/usr/bin/env python3
"""Analyse a passive USRP capture and report the tail behaviour per transmission."""

import json
import math
import struct
import sys

import mmdvm_dsp as D

SAMPLE_RATE = 8000
FRAME = 160


def read_capture(path):
    packets = []
    with open(path, "rb") as handle:
        data = handle.read()
    pos = 0
    while pos + 12 <= len(data):
        ts, length = struct.unpack("<dI", data[pos:pos + 12])
        pos += 12
        payload = data[pos:pos + length]
        pos += length
        if len(payload) != length:
            break
        packets.append((ts, payload))
    return packets


def parse(payload):
    if len(payload) < 32 or payload[0:4] != b"USRP":
        return None
    return {
        "seq": struct.unpack(">I", payload[4:8])[0],
        "ptt": struct.unpack(">I", payload[12:16])[0],
        "type": struct.unpack(">I", payload[20:24])[0],
        "audio": payload[32:],
    }


def flatness(samples):
    """Geometric over arithmetic mean of the band energies, 1 is noise like."""
    if len(samples) < 32:
        return 0.0
    freqs = [300.0 + 120.0 * i for i in range(20)]
    energies = []
    for f in freqs:
        e = D.goertzel(samples, f, SAMPLE_RATE)
        energies.append(max(e, 1e-12))
    log_sum = sum(math.log(e) for e in energies) / len(energies)
    arith = sum(energies) / len(energies)
    if arith <= 0.0:
        return 0.0
    return math.exp(log_sum) / arith


def transmissions(packets):
    result = []
    current = None
    for (ts, payload) in packets:
        info = parse(payload)
        if info is None:
            continue
        if info["type"] == 2:
            current = {"start": ts, "audio": [], "stamps": [], "end": None,
                       "seqs": []}
            result.append(current)
        elif info["type"] == 0:
            if current is None:
                current = {"start": ts, "audio": [], "stamps": [], "end": None,
                           "seqs": []}
                result.append(current)
            current["seqs"].append(info["seq"])
            if info["ptt"] == 1 and info["audio"]:
                n = len(info["audio"]) // 2
                current["audio"].extend(
                    struct.unpack("<%dh" % n, info["audio"][:n * 2]))
                current["stamps"].append(ts)
            elif info["ptt"] == 0:
                current["end"] = ts
    return result


def analyse(path):
    packets = read_capture(path)
    tx = transmissions(packets)
    rows = []
    for item in tx:
        samples = [v / 32768.0 for v in item["audio"]]
        if len(samples) < FRAME * 5:
            continue
        env = D.frame_rms(samples)
        peak = max(env) if env else 0.0
        threshold = max(0.004, peak * 0.12)
        last_loud = 0
        for index, value in enumerate(env):
            if value >= threshold:
                last_loud = index
        tail_frames = len(env) - 1 - last_loud
        tail_start = last_loud * FRAME
        last_100 = samples[-int(0.1 * SAMPLE_RATE):]
        last_40 = samples[-int(0.04 * SAMPLE_RATE):]
        rows.append({
            "duration_s": round(len(samples) / float(SAMPLE_RATE), 3),
            "frames": len(env),
            "peak_rms": round(peak, 4),
            "last_loud_frame": last_loud,
            "quiet_tail_ms": tail_frames * 20,
            "last_100ms_rms": round(D.rms(last_100), 4),
            "last_40ms_rms": round(D.rms(last_40), 4),
            "last_100ms_flatness": round(flatness(last_100), 4),
            "last_40ms_flatness": round(flatness(last_40), 4),
            "end_gap_ms": round((item["end"] - item["stamps"][-1]) * 1000.0, 1)
                         if item["end"] and item["stamps"] else None,
        })
    return rows


def main():
    path = sys.argv[1]
    rows = analyse(path)
    print("capture: %s" % path)
    print("complete transmissions analysed: %d" % len(rows))
    for index, row in enumerate(rows):
        print("  #%d %s" % (index + 1, json.dumps(row, sort_keys=True)))
    if rows:
        def avg(key):
            return sum(r[key] for r in rows) / float(len(rows))
        print("")
        print("mean last 100 ms RMS        : %.4f" % avg("last_100ms_rms"))
        print("mean last 100 ms flatness   : %.4f" % avg("last_100ms_flatness"))
        print("mean quiet tail             : %.1f ms" % avg("quiet_tail_ms"))
        print("mean transmission duration  : %.2f s" % avg("duration_s"))


if __name__ == "__main__":
    main()
