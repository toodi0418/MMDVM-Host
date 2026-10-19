#!/usr/bin/env python3
"""Core harness for the R1 FM squelch tail elimination tests.

The real MMDVMHost binary is started against an emulated MMDVM modem that is
attached to a PTY. The USRP stream produced by the host is captured on the
loopback interface. Nothing ever leaves the machine and the production
MMDVMHost service is not touched.
"""

import os
import pty
import select
import socket
import struct
import subprocess
import threading
import time

FRAME_START = 0xE0

CMD_GET_VERSION = 0x00
CMD_GET_STATUS = 0x01
CMD_SET_CONFIG = 0x02
CMD_SET_MODE = 0x03
CMD_SET_FREQ = 0x04
CMD_FM_PARAMS1 = 0x60
CMD_FM_PARAMS2 = 0x61
CMD_FM_PARAMS3 = 0x62
CMD_FM_PARAMS4 = 0x63
CMD_FM_DATA = 0x65
CMD_FM_CONTROL = 0x66
CMD_FM_EOT = 0x67
CMD_ACK = 0x70
CMD_NAK = 0x7F

ACK_REQUIRED = set([CMD_SET_CONFIG, CMD_SET_FREQ,
                    CMD_FM_PARAMS1, CMD_FM_PARAMS2,
                    CMD_FM_PARAMS3, CMD_FM_PARAMS4])

SAMPLE_RATE = 8000
FRAME_SAMPLES = 160          # 20 ms of FM audio per modem frame
FRAME_MS = 1000.0 * FRAME_SAMPLES / SAMPLE_RATE


def build_frame(ftype, payload=b""):
    return bytes([FRAME_START, 3 + len(payload), ftype]) + bytes(payload)


def to12(value):
    v = int(round(value * 2047.0)) + 2048
    if v < 0:
        v = 0
    if v > 4095:
        v = 4095
    return v


def pack_samples(samples):
    """Pack 12-bit offset binary samples two per three bytes, as the MMDVM does."""
    out = bytearray()
    n = len(samples) - (len(samples) % 2)
    i = 0
    while i < n:
        pack = (to12(samples[i]) << 12) | to12(samples[i + 1])
        out.append(pack & 0xFF)
        out.append((pack >> 8) & 0xFF)
        out.append((pack >> 16) & 0xFF)
        i += 2
    return bytes(out)


def unpack_samples(payload):
    """Inverse of pack_samples, returns signed 12-bit values."""
    out = []
    n = len(payload) - (len(payload) % 3)
    i = 0
    while i < n:
        pack = payload[i] | (payload[i + 1] << 8) | (payload[i + 2] << 16)
        out.append((pack & 0x0FFF) - 2048)
        out.append(((pack >> 12) & 0x0FFF) - 2048)
        i += 3
    return out


def parse_usrp(data):
    if len(data) < 32 or data[0:4] != b"USRP":
        return None
    return {
        "seq": struct.unpack(">I", data[4:8])[0],
        "ptt": struct.unpack(">I", data[12:16])[0],
        "type": struct.unpack(">I", data[20:24])[0],
        "payload": data[32:],
        "length": len(data),
    }


class ModemEmulator(threading.Thread):
    """Emulates the MMDVM modem using the MMDVMHost UDP modem port type.

    MMDVMHost sends its serial frames to emulator_port and accepts the replies
    on host_port, so no serial hardware or PTY is involved.
    """

    def __init__(self, emulator_port, host_port):
        super(ModemEmulator, self).__init__()
        self.daemon = True
        self.emulator_port = emulator_port
        self.host_addr = ("127.0.0.1", host_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", emulator_port))
        self.sock.settimeout(0.1)
        self._buf = bytearray()
        self._write_lock = threading.Lock()
        self._lock = threading.Lock()
        self.rx_frames = []
        self.version_seen = threading.Event()
        self.config_seen = threading.Event()
        self.running = True
        self.error = None

    # -- writing -----------------------------------------------------------
    def send_frame(self, ftype, payload=b""):
        frame = build_frame(ftype, payload)
        with self._write_lock:
            try:
                self.sock.sendto(frame, self.host_addr)
            except OSError as exc:
                self.error = exc

    def send_fm_data(self, samples):
        self.send_frame(CMD_FM_DATA, pack_samples(samples))

    def send_fm_eot(self):
        self.send_frame(CMD_FM_EOT)

    def send_fm_control(self, payload=b"\x00\x00\x00\x00"):
        self.send_frame(CMD_FM_CONTROL, payload)

    # -- reading -----------------------------------------------------------
    def run(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                continue
            self._buf.extend(data)
            self._parse()

    def _parse(self):
        while True:
            if len(self._buf) < 2:
                return
            if self._buf[0] != FRAME_START:
                del self._buf[0]
                continue
            length = self._buf[1]
            offset = 2
            if length == 0:
                if len(self._buf) < 3:
                    return
                length = self._buf[2] + 255
                offset = 3
            if length > 600 or length < (offset + 1):
                del self._buf[0]
                continue
            if len(self._buf) < length:
                return
            frame = bytes(self._buf[:length])
            del self._buf[:length]
            ftype = frame[offset]
            payload = frame[offset + 1:]
            with self._lock:
                self.rx_frames.append((time.monotonic(), ftype, payload))
            self._handle(ftype, payload)

    def _handle(self, ftype, payload):
        if ftype == CMD_GET_VERSION:
            self.send_frame(CMD_GET_VERSION, self._version_payload())
            self.version_seen.set()
        elif ftype == CMD_SET_CONFIG:
            self.send_frame(CMD_ACK)
            self.config_seen.set()
        elif ftype in ACK_REQUIRED:
            self.send_frame(CMD_ACK)
        elif ftype == CMD_GET_STATUS:
            self.send_frame(CMD_GET_STATUS, self._status_payload())

    @staticmethod
    def _status_payload():
        # protocol 2 status: [0]=mode [1]=flags [2]=unused
        # [3]=D-Star [4]=DMR1 [5]=DMR2 [6]=YSF [7]=P25 [8]=NXDN [9]=M17
        # [10]=FM [11]=POCSAG [12]=AX.25 space
        out = bytearray(13)
        out[10] = 200            # room for downlink FM audio
        return bytes(out)

    @staticmethod
    def _version_payload():
        # protocol 2: [3]=version [4]=caps1 [5]=caps2 [6]=cpu [7..22]=udid [23..]=text
        caps1 = 0x40 | 0x02      # FM and DMR
        caps2 = 0x00
        out = bytearray()
        out.append(2)
        out.append(caps1)
        out.append(caps2)
        out.append(2)            # ST-Micro
        out.extend(bytes([0x2C, 0x00, 0x47, 0x00, 0x11, 0x50,
                          0x30, 0x50, 0x30, 0x34, 0x39, 0x20,
                          0x00, 0x00, 0x00, 0x00]))
        out.extend(b"MMDVM TEST 20240210")
        return bytes(out)

    # -- helpers -----------------------------------------------------------
    def frames_of(self, ftype):
        with self._lock:
            return [(ts, p) for (ts, t, p) in self.rx_frames if t == ftype]

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class UsrpCapture(threading.Thread):
    """Collects the USRP stream that MMDVMHost sends to the gateway."""

    def __init__(self, port):
        super(UsrpCapture, self).__init__()
        self.daemon = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.2)
        self.packets = []
        self._lock = threading.Lock()
        self.running = True

    def run(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            ts = time.monotonic()
            with self._lock:
                self.packets.append((ts, data))

    def snapshot(self):
        with self._lock:
            return list(self.packets)

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class HostRunner(object):
    """Runs MMDVMHost with its own configuration and captures its log."""

    def __init__(self, binary, ini_path, workdir):
        self.binary = binary
        self.ini_path = ini_path
        self.workdir = workdir
        self.proc = None
        self.log_lines = []
        self._log_lock = threading.Lock()

    def start(self):
        self.proc = subprocess.Popen(
            [self.binary, self.ini_path],
            cwd=self.workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True)
        reader = threading.Thread(target=self._read_log)
        reader.daemon = True
        reader.start()

    def _read_log(self):
        try:
            for line in self.proc.stdout:
                with self._log_lock:
                    self.log_lines.append(line.rstrip("\n"))
        except Exception:
            pass

    def log_text(self):
        with self._log_lock:
            return "\n".join(self.log_lines)

    def wait_for_log(self, needle, timeout=15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.log_text():
                return True
            if self.proc.poll() is not None:
                return False
            time.sleep(0.05)
        return False

    def rss_kb(self):
        try:
            with open("/proc/%d/status" % self.proc.pid) as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except (IOError, OSError, ValueError):
            pass
        return None

    def stop(self, grace=2.0):
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            end = time.monotonic() + grace
            while time.monotonic() < end and self.proc.poll() is None:
                time.sleep(0.05)
            if self.proc.poll() is None:
                self.proc.kill()
        try:
            self.proc.wait(timeout=2)
        except Exception:
            pass


def stream_audio(modem, samples, t0=None):
    """Send samples at 20 ms cadence, returns the time the last frame was sent."""
    t0 = time.monotonic() if t0 is None else t0
    index = 0
    frame_no = 0
    total = len(samples)
    while index < total:
        chunk = list(samples[index:index + FRAME_SAMPLES])
        while len(chunk) < FRAME_SAMPLES:
            chunk.append(0.0)
        target = t0 + frame_no * (FRAME_MS / 1000.0)
        now = time.monotonic()
        if target > now:
            time.sleep(target - now)
        modem.send_fm_data(chunk)
        index += FRAME_SAMPLES
        frame_no += 1
    return t0 + frame_no * (FRAME_MS / 1000.0)


def collect_audio(capture, min_samples=0, timeout=3.0):
    """Wait until the USRP audio has settled, returns the audio packets."""
    last_count = -1
    stable_since = time.monotonic()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        packets = capture.snapshot()
        count = len(packets)
        if count == last_count:
            if time.monotonic() - stable_since > 0.35:
                total = sum(1 for (_, d) in packets if is_audio(d))
                if total >= min_samples:
                    break
        else:
            last_count = count
            stable_since = time.monotonic()
        time.sleep(0.05)
    return capture.snapshot()


def is_audio(data):
    info = parse_usrp(data)
    return (info is not None and info["type"] == 0 and info["ptt"] == 1
            and len(info["payload"]) >= 2)


def is_end(data):
    info = parse_usrp(data)
    return info is not None and info["type"] == 0 and info["ptt"] == 0


def decode_audio(packets):
    """Concatenate all USRP PTT-on audio payloads into a list of floats."""
    out = []
    for (_, data) in packets:
        info = parse_usrp(data)
        if info is None or info["type"] != 0 or info["ptt"] != 1:
            continue
        payload = info["payload"]
        n = len(payload) // 2
        if n == 0:
            continue
        samples = struct.unpack("<%dh" % n, payload[:n * 2])
        for value in samples:
            out.append(value / 32767.0)
    return out
