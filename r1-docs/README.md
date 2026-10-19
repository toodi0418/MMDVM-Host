# R1 MMDVMHost FM Squelch Tail Elimination

Customisation of MMDVMHost for the R1 Keelung FM repeater. It adds an optional
delay line on the FM RF to USRP uplink so that the squelch tail produced when
the RF carrier drops is thrown away instead of being forwarded to the
AllStarLink hub.

* Base upstream commit: `218a017956b174334a2fe0418e373ba139768f5f` (2024-02-09)
* Development branch: `r1-fm-tail-elim`
* Target platform: Raspberry Pi 3 Model B, Raspbian 11 (armv7l), Pi-Star 4.2.3

Everything described here only touches the **FM RF to USRP uplink**. The USRP
to RF downlink, the USRP packet format, DMR, D-Star, YSF, P25, NXDN, M17,
POCSAG and AX.25 paths are unchanged.

---

## 1. How it works

The uplink path before the change:

```
RF -> modem (UART/UDP) -> CModem::readFMData() -> CFMControl::writeModem()
   -> unpack, de-emphasis, 300-2700 Hz filter -> CFMNetwork::writeData()
   -> CFMNetwork::writeUSRPData() -> UDP -> ASL hub
```

`CFMControl::writeModem()` already receives the end of transmission marker
(`TAG_EOT`) from the modem and calls `CFMNetwork::writeEnd()`. The change adds a
fixed size delay line between the filter chain and the network:

```
audio frames -> filter chain -> [ delay line D samples ] -> CFMNetwork::writeData()
                                                  |
                       TAG_EOT -> discard the delay line, then writeEnd()
```

* Every transmission starts with the delay line pre-filled with `D` samples of
  silence. The number of samples released always equals the number of samples
  received, so the 20 ms USRP packet cadence is unchanged and audio is never
  sent in a burst.
* When the modem reports the end of the RF transmission the audio still inside
  the delay line has not been sent yet; it is dropped and the USRP PTT-off
  packet is sent immediately. The squelch tail never leaves the repeater.
* The delay line is also cleared when FM mode is left, and after a 300 ms gap
  without audio (a lost EOT), so audio can never leak from one transmission
  into the next.
* The line is a single fixed size allocation made at start up. There is no
  queue that can grow and no per-frame allocation.

### Trade-off that the operator must understand

With a delay of `D` ms and an actual squelch tail of `T` ms measured from the
end of speech to the EOT reported by the modem:

* tail removed = `min(T, D)`
* speech truncated = `max(0, D - T)`
* added uplink latency = `D` (on top of the ~100 ms that the MMDVM firmware
  already adds in AccessMode=1)

So `SquelchTailElimMs` should be set close to the real tail length of the
repeater. With `D = 200 ms` a tail of 200 ms or longer is removed completely
and no speech is cut. If the tail is only 50 ms, a 200 ms delay removes the
tail but also cuts 150 ms of speech, which the automated tests quantify.

The automated test suite measures all of this from the USRP stream itself, see
section 6.

---

## 2. Configuration reference

New keys in the `[FM Network]` section of the MMDVMHost configuration file
(`/etc/mmdvmhost` on Pi-Star):

| Key | Values | Default | Meaning |
|---|---|---|---|
| `SquelchTailElim` | `0` / `1` | `0` | Enable the delay line and the tail chop |
| `SquelchTailElimMs` | `20` - `500` | `200` | Delay length in milliseconds, 8 samples per ms |

Rules:

* The feature is **off by default**, so an untouched configuration behaves
  exactly like upstream MMDVMHost.
* `SquelchTailElim=1` without `SquelchTailElimMs` uses 200 ms.
* Values outside 20 - 500 ms are clamped to the range and a warning is logged:
  `SquelchTailElimMs=... is below the minimum of 20ms, using the minimum`.
* Non numeric values are read as 0 and therefore clamped to the minimum with
  the same warning.
* When enabled the effective values are logged at start up:

```
I:     Squelch Tail Elim: yes
I:     Squelch Tail Elim Delay: 200ms
```

Example:

```ini
[FM Network]
Enable=1
Protocol=USRP
SampleRate=8000
LocalAddress=172.16.8.252
LocalPort=34003
GatewayAddress=10.37.60.3
GatewayPort=32003
PreEmphasis=1
DeEmphasis=1
TXAudioGain=0.05
RXAudioGain=1.0
ModeHang=3
Debug=0
SquelchTailElim=1
SquelchTailElimMs=200
```

A configuration change takes effect after restarting MMDVMHost:

```bash
sudo systemctl restart mmdvmhost
```

> Reminder for Pi-Star: `(` `)` `[` `]` must not appear in comments inside
> `/etc/mmdvmhost`, the dashboard PHP parser rejects the whole file.

---

## 3. Source changes

| File | Change |
|---|---|
| `Conf.h` / `Conf.cpp` | Two new `[FM Network]` keys, getters, defaults `0` / `200` |
| `FMControl.h` / `FMControl.cpp` | Fixed size delay line, priming, chop on EOT, reset on mode change and on a 300 ms gap |
| `MMDVMHost.h` / `MMDVMHost.cpp` | Pass the validated settings to `CFMControl`, log the effective values, warn on out of range values |

Nothing else is modified. `CFMNetwork`, the USRP packet layout and the modem
interface are untouched.

---

## 4. Building on the target (R1)

The build is done natively on the Raspberry Pi; cross compilation is not used.
Pi-Star does not ship the `libsamplerate` development header, but the runtime
library is present, so the header is taken from the Debian package without
installing anything into the system:

```bash
mkdir -p ~/r1-tail-elim && cd ~/r1-tail-elim
apt-get download libsamplerate0-dev          # no root needed, writes a .deb here
dpkg-deb -x libsamplerate0-dev_*_armhf.deb devpkg

git clone --branch r1-fm-tail-elim https://github.com/toodi0418/MMDVM-Host.git src
cd src
make -j2 \
  CFLAGS="-g -O3 -Wall -std=c++0x -pthread -DHAVE_LOG_H -I/usr/local/include -I$HOME/r1-tail-elim/devpkg/usr/include" \
  LDFLAGS="-g -L/usr/local/lib -L$HOME/r1-tail-elim/devpkg/usr/lib/arm-linux-gnueabihf"

strip MMDVMHost          # optional, the shipped binary is stripped
./MMDVMHost --version    # MMDVMHost version 20240207 git #<commit>
```

Notes:

* `-j2` is deliberate. The Pi 3 has 1 GB of RAM; a higher parallelism risks the
  out of memory killer.
* The ArduiPi_OLED and wiringPi headers needed by the Pi-Star build are present
  in `/usr/local/include` and `/usr/include`, the generic upstream Makefile does
  not enable the OLED display so they are not used.
* The build directory must not be `/tmp` on Pi-Star, it is a 64 MB tmpfs.
  `/dev/shm` is also unreliable on this image. Use a directory on the root
  filesystem while it is temporarily remounted read write.
* The `libsamplerate0-dev` package only contains the static archive and a
  dangling `libsamplerate.so` symlink, so `-lsamplerate` links the 0.2.1 static
  library into the binary. That version matches the `libsamplerate.so.0.2.1`
  that Pi-Star ships, and it removes the runtime dependency. The USRP path does
  not call the resampler at all, it is only used by the RAW FM protocol.

---

## 5. Deployment on R1

### 5.1 Backup first

```bash
sudo mount -o remount,rw /
sudo mkdir -p /root/r1-backup
sudo cp -a /usr/local/bin/MMDVMHost        /root/r1-backup/MMDVMHost.orig
sudo cp -a /etc/mmdvmhost                  /root/r1-backup/mmdvmhost.ini.orig
sudo cp -a /lib/systemd/system/mmdvmhost.service /root/r1-backup/mmdvmhost.service.orig
sudo cp -a /usr/local/sbin/mmdvmhost.service     /root/r1-backup/mmdvmhost.launcher.orig
sudo sha256sum /root/r1-backup/MMDVMHost.orig
```

### 5.2 Install the binary and the configuration

```bash
sudo cp -f MMDVMHost /usr/local/bin/MMDVMHost
sudo chmod 755 /usr/local/bin/MMDVMHost
sudo chown root:bin /usr/local/bin/MMDVMHost

# add the two keys to the existing [FM Network] section
sudo python3 - <<PY
path = "/etc/mmdvmhost"
text = open(path).read()
if "SquelchTailElim=" not in text:
    text = text.replace("[FM Network]\n",
                        "[FM Network]\nSquelchTailElim=1\nSquelchTailElimMs=200\n", 1)
    open(path, "w").write(text)
PY

sudo systemctl restart mmdvmhost
sudo mount -o remount,ro /
```

### 5.3 Verify

```bash
systemctl is-active mmdvmhost
sudo tail -40 /var/log/pi-star/MMDVM-$(date -u +%F).log
sudo ss -lunp | grep 34003
/usr/local/bin/MMDVMHost --version
sha256sum /usr/local/bin/MMDVMHost
```

Expected in the log:

```
I:     Squelch Tail Elim: yes
I:     Squelch Tail Elim Delay: 200ms
M: Opening FM network connection
I: Opening UDP port on 34003
I: MMDVMHost-... is running
```

### 5.4 Persistence against Pi-Star updates

`/usr/local/bin` is a git repository that Pi-Star pulls every day at around
04:30 (`git --work-tree=/usr/local/bin --git-dir=/usr/local/bin/.git pull`).
Two things can happen:

* Upstream does not change `MMDVMHost`: the pull fast forwards and our modified
  file stays in place as a local modification.
* Upstream does change `MMDVMHost`: the pull refuses to overwrite the modified
  file and aborts, so our binary is still not replaced (the bin repository just
  stays at the previous commit).

In both cases the file survives, but a manual `git checkout`/`reset`, an apt
reinstall or a Pi-Star image upgrade could replace it. Two small helpers keep
the custom binary in place with minimal intrusion:

* `/usr/local/etc/r1-tail-elim/restore-binary.sh` compares the SHA256 of the
  installed binary with the stored one and copies the stored binary back when
  they differ. It logs to `/var/log/r1-tail-elim.log` and never restarts the
  service on its own.
* A `post-merge` hook in `/usr/local/bin/.git/hooks` runs the same script after
  a successful `git pull`, so the custom binary is back before Pi-Star starts
  the service again at the end of the daily run.
* `r1-tail-elim-verify.timer` runs the script every 10 minutes as a catch-all.

Install them with `r1-deploy/persist-install.sh`.

---

## 6. Automated test suite

The suite runs the **real compiled MMDVMHost binary** against an emulated
MMDVM modem talking the MMDVM serial protocol over the built in UDP modem port
(`[Modem] Protocol=udp`). The USRP stream is captured on the loopback
interface. No RF is transmitted, no packet reaches the production hub and the
running MMDVMHost service is never touched.

```bash
cd ~/r1-tail-elim/test
python3 run_tests.py
```

Reports are written to `results/`.

What it verifies:

see `r1-docs/TEST-PLAN.md`.

The comparison case needs two binaries with the same toolchain: the modified
one in the checkout root and an unmodified baseline built from the same base
commit in a sibling directory:

```bash
git -C src worktree add -f ../baseline 218a017956b174334a2fe0418e373ba139768f5f
cd ../baseline && make -j2 ...        # same flags as above
```

The suite looks for `../baseline/MMDVMHost` by default; override with
`MMDVM_MODIFIED` and `MMDVM_BASELINE` environment variables if the layout is
different.

---

## 7. Rollback

```bash
sudo ~/r1-tail-elim/src/r1-deploy/rollback.sh
```

It restores `/root/r1-backup/MMDVMHost.orig` and
`/root/r1-backup/mmdvmhost.ini.orig`, restarts the service and prints the
resulting version and SHA256. See `r1-deploy/rollback.sh` for the exact steps.
