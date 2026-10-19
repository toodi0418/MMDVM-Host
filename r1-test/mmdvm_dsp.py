#!/usr/bin/env python3
"""Signal analysis helpers for the FM squelch tail elimination tests.

The host DSP chain of MMDVMHost 218a017 is reproduced here with the exact
coefficients used by FMControl.cpp so that the audio captured on the USRP side
can be compared, sample by sample, with the audio that was injected at the
modem side.
"""

import math

SAMPLE_RATE = 8000
FRAME_SAMPLES = 160

DEEMPH_B = (0.07708787090460224, 0.07708787090460224, 0.0)
DEEMPH_A = (-0.8458242581907955, 0.0)
DEEMPH_GAIN = 10.0 ** (8.0 / 20.0)

STAGES = (
    ((0.29495028, 0.0, -0.29495028), (-0.61384624, -0.057158668)),
    ((1.0, 2.0, 1.0), (0.9946123, 0.6050482)),
    ((1.0, -2.0, 1.0), (-1.8414584, 0.8804949)),
)
STAGE_GAIN = 10.0 ** (2.0 / 20.0)


def _iir(samples, b, a, gain):
    x1 = x2 = y1 = y2 = 0.0
    out = []
    append = out.append
    b0, b1, b2 = b
    a1, a2 = a
    for x in samples:
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        y2 = y1
        x1 = x
        y1 = y          # the feedback uses the value before the gain
        append(y * gain)
    return out


def host_filter(samples, deemphasis=True):
    """Reproduce the MMDVMHost FM uplink DSP chain."""
    data = list(samples)
    if deemphasis:
        data = _iir(data, DEEMPH_B, DEEMPH_A, DEEMPH_GAIN)
    for (b, a) in STAGES:
        data = _iir(data, b, a, STAGE_GAIN)
    return data


def rms(samples):
    if not samples:
        return 0.0
    total = 0.0
    for value in samples:
        total += value * value
    return math.sqrt(total / len(samples))


def peak(samples):
    if not samples:
        return 0.0
    return max(max(samples), -min(samples))


def frame_rms(samples, frame=FRAME_SAMPLES):
    out = []
    for index in range(0, len(samples) - frame + 1, frame):
        out.append(rms(samples[index:index + frame]))
    return out


def normalise(values):
    if not values:
        return []
    mean = sum(values) / len(values)
    centred = [value - mean for value in values]
    dev = math.sqrt(sum(value * value for value in centred) / len(centred))
    if dev == 0.0:
        return [0.0] * len(values)
    return [value / dev for value in centred]


def _pearson(a, b):
    n = len(a)
    if n < 2:
        return 0.0
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = 0.0
    den_a = 0.0
    den_b = 0.0
    for x, y in zip(a, b):
        xc = x - mean_a
        yc = y - mean_b
        num += xc * yc
        den_a += xc * xc
        den_b += yc * yc
    if den_a <= 0.0 or den_b <= 0.0:
        return 0.0
    return num / math.sqrt(den_a * den_b)


def best_lag(reference, measured, max_lag, min_overlap=8):
    """Return the lag, in frames, that best aligns measured with reference.

    A positive lag means that measured is delayed by that many frames. Each
    candidate lag is scored with the Pearson correlation of the overlapping
    part only, so that short overlaps cannot produce a spurious peak.
    """
    best = 0
    best_score = -2.0
    for lag in range(-max_lag, max_lag + 1):
        a = []
        b = []
        for index in range(len(reference)):
            other = index + lag
            if other < 0 or other >= len(measured):
                continue
            a.append(reference[index])
            b.append(measured[other])
        if len(a) < min_overlap:
            continue
        score = _pearson(a, b)
        if score > best_score:
            best_score = score
            best = lag
    return best, best_score


def goertzel(samples, freq, sample_rate=SAMPLE_RATE):
    n = len(samples)
    if n == 0 or freq <= 0.0:
        return 0.0
    k = int(0.5 + (n * freq) / sample_rate)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)
    s0 = s1 = s2 = 0.0
    for value in samples:
        s0 = value + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return power / (n * n)


def band_energy(samples, freqs, sample_rate=SAMPLE_RATE):
    return sum(goertzel(samples, f, sample_rate) for f in freqs)


def tonality(samples, tones, sample_rate=SAMPLE_RATE):
    """Ratio of energy in the expected tones to the total signal energy."""
    total = rms(samples)
    if total <= 0.0:
        return 0.0
    total_power = total * total
    tone_power = band_energy(samples, tones, sample_rate)
    if total_power <= 0.0:
        return 0.0
    return min(1.0, tone_power / total_power)


def difference_energy_ratio(samples):
    """High frequency content, a cheap discriminator between noise and tones."""
    if len(samples) < 2:
        return 0.0
    total = 0.0
    diff = 0.0
    for index in range(1, len(samples)):
        total += samples[index] * samples[index]
        delta = samples[index] - samples[index - 1]
        diff += delta * delta
    if total <= 0.0:
        return 0.0
    return diff / total


def correlation(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    num = 0.0
    den_a = 0.0
    den_b = 0.0
    for x, y in zip(a, b):
        xc = x - mean_a
        yc = y - mean_b
        num += xc * yc
        den_a += xc * xc
        den_b += yc * yc
    if den_a <= 0.0 or den_b <= 0.0:
        return 0.0
    return num / math.sqrt(den_a * den_b)


def segment(samples, start_sample, length):
    if start_sample < 0:
        start_sample = 0
    return samples[start_sample:start_sample + length]
