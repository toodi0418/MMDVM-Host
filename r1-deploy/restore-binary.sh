#!/bin/bash
#
# Re-install the R1 squelch tail elimination MMDVMHost binary when something
# (Pi-Star daily update, git checkout, apt, image upgrade) has replaced it.
# It never restarts mmdvmhost on its own.

STORE=${STORE:-/usr/local/etc/r1-tail-elim}
TARGET=/usr/local/bin/MMDVMHost
STASHA=$STORE/MMDVMHost.sha256
LOG=/var/log/r1-tail-elim.log

[ -x "$STORE/MMDVMHost.r1tail" ] || exit 0
[ -r "$STASHA" ] || exit 0

expected=$(cat "$STASHA")
current=""
if [ -f "$TARGET" ]; then
    current=$(sha256sum "$TARGET" 2>/dev/null | awk "{print \$1}")
fi

if [ "$current" = "$expected" ]; then
    exit 0
fi

remount_ro=0
if mount | grep -qE "^/dev/.* on / type ext4 \(ro"; then
    remount_ro=1
    mount -o remount,rw / >/dev/null 2>&1
fi

cp -f "$STORE/MMDVMHost.r1tail" "$TARGET"
chmod 755 "$TARGET"
chown root:bin "$TARGET"

if [ "$remount_ro" = "1" ]; then
    mount -o remount,ro / >/dev/null 2>&1
fi

echo "$(date -Is) MMDVMHost had sha ${current:-missing} instead of ${expected}, restored the R1 tail elimination binary" >> "$LOG"
exit 0
