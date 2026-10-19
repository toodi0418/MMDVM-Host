# R2 deployment record

Station: R2 (10.37.72.1), Pi-Star 4.1.6, Raspbian 10 (buster), glibc 2.28,
Raspberry Pi 4, gcc 8.3.0. Deployed 2026-10-19 21:33:23 CST at the request of
the operator, after R1.

## Why R2 needs its own build

The R1 binary is built on bullseye and needs glibc 2.31. R2 runs buster with
glibc 2.28, so the R1 binary would not start there. R2 was therefore built
natively, with the gcc 8.3.0 that Pi-Star itself uses, and with the same
`OLED=1` option (the OLED define is what keeps the daemon from dropping root
and failing to open the root owned log).

## Build (native on R2)

```bash
WORK=$HOME/r2-build; mkdir -p $WORK && cd $WORK
apt-get download libsamplerate0-dev          # no root, writes a .deb here
dpkg-deb -x libsamplerate0-dev_*.deb devpkg   # nothing is installed
git clone --branch r1-fm-tail-elim https://github.com/toodi0418/MMDVM-Host.git src
cd src && git worktree add -f ../baseline 218a017956b174334a2fe0418e373ba139768f5f
export CPLUS_INCLUDE_PATH=$WORK/devpkg/usr/include
export LIBRARY_PATH=$WORK/devpkg/usr/lib/arm-linux-gnueabihf
make -j3 OLED=1                               # and the same for baseline
strip --strip-unneeded MMDVMHost
```

Result: `MMDVMHost version 20240207 git #4f45d99`,
SHA256 `21cdd3eb741db69b79dbc923b7461c13a097df0f402b2e8759c020127787e477`,
statically linked libsamplerate 0.1.9 (the buster dev package only ships the
static archive, same situation as on R1).

## Tests

The full 15 case suite was run on R2 against the R2 build before deploying:
**15/15 PASS**, including the compatibility case against an R2 built baseline
binary from commit 218a017.

## Deployment

* Backup in `/root/r2-backup`: original `MMDVMHost` (SHA `75584e59...`), the
  INI, the systemd unit and the launcher script.
* The first attempt failed at the health check: `deploy.sh` extracted the FM
  LocalPort with `awk` without `-F=`, so it read an empty value and aborted.
  The **automatic rollback restored the original binary** within seconds
  (21:29:29). The script was fixed and pushed.
* Second attempt: **successful 21:33:23**, health checks passed (service
  active, `Squelch Tail Elim` logged, USRP socket 34102 bound, 30 s stability
  window), 0 error lines afterwards.
* Persistence: `/usr/local/etc/r2-tail-elim` (binary + SHA256 + restore and
  rollback scripts), `/usr/local/bin/.git/hooks/post-merge`,
  `/etc/cron.d/r2-tail-elim`. Tested: hash match, no spurious action.

## Tail length measurement and the 400 ms setting

R2 sends its USRP uplink to the local AGC proxy (`127.0.0.1:32002`), so the
passive capture runs on `lo` with `sport 34102, dport 32002`.

With the feature disabled, five complete transmissions were captured:

| duration | terminal loud segment | end periodicity | mid speech periodicity |
|---|---|---|---|
| 10.8 s | 360 ms | 0.21 - 0.32 | 0.61 - 0.72 |
| 7.0 s | 440 ms | 0.19 - 0.31 | 0.21 - 0.37 |
| 6.5 s | 280 ms | 0.19 - 0.25 | 0.21 - 0.25 |
| 7.0 s | 480 ms | 0.31 - 0.45 | 0.45 - 0.58 |
| 5.1 s | 20 ms | 0.18 - 0.33 | 0.34 - 0.50 |

The terminal loud segment is **280 - 480 ms, mean 316 ms**, and its pitch
periodicity is lower than mid speech, so it is receiver noise and not speech.
200 ms therefore left an audible residual.

`SquelchTailElimMs` was raised to **400 ms** and verified, but the operator
then chose to go back to **200 ms** for a longer observation period before
deciding on a permanent value. The measurements and the 400 ms verification
below are kept so that the decision can be made later with the data at hand.

The deployed R2 binary was then verified against the measured tail lengths with
the offline harness:

| D | T | waveform correlation | measured delay | residual tail | speech cut |
|---|---|---|---|---|---|
| 400 | 280 | 1.000000 | 400 ms | 0 ms | 120 ms |
| 400 | 480 | 1.000000 | 400 ms | 80 ms | 0 ms |
| 400 | 200 | 1.000000 | 400 ms | 0 ms | 200 ms |
| 400 | 700 | 1.000000 | 400 ms | 300 ms | 0 ms |

A 400 ms delay removes the whole tail for the 280 ms case, leaves 80 ms for the
480 ms case, and costs 120 ms of speech when the tail is only 280 ms.

## Current state

Service active, `SquelchTailElim=1`, **`SquelchTailElimMs=200`** (400 ms was
tried and reverted for long term observation), USRP socket `127.0.0.1:34102`
bound, AGC proxy untouched on `127.0.0.1:32002`, root filesystem back to read
only.
