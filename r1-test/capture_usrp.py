#!/usr/bin/env python3
"""Passive USRP uplink capture for the R1 repeater.

Reads the packets that MMDVMHost sends to the ASL hub with an AF_PACKET
socket. Nothing is transmitted and the running service is not disturbed.
"""

import os
import socket
import struct
import sys
import time

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/pi-star/r1-tail-elim/capture.bin"
IFACE = sys.argv[3] if len(sys.argv) > 3 else "eth0"

sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
sock.bind((IFACE, 0))
sock.settimeout(0.5)

start = time.monotonic()
count = 0
with open(OUT, "wb") as handle:
    while time.monotonic() - start < DURATION:
        try:
            frame, _ = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        if len(frame) < 42:
            continue
        if struct.unpack("!H", frame[12:14])[0] != 0x0800:
            continue
        ip = frame[14:]
        if (ip[0] >> 4) != 4 or ip[9] != 17:
            continue
        ihl = (ip[0] & 0x0F) * 4
        udp = ip[ihl:]
        if len(udp) < 8:
            continue
        sport, dport, ulen = struct.unpack("!HHH", udp[:6])
        if dport != 32003 or sport != 34003:
            continue
        payload = udp[8:ulen]
        if not payload.startswith(b"USRP"):
            continue
        ts = time.monotonic() - start
        handle.write(struct.pack("<dI", ts, len(payload)))
        handle.write(payload)
        count += 1

print("captured %d packets in %.0f s to %s" % (count, time.monotonic() - start, OUT))
