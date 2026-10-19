#!/bin/bash
#
# Restore the original Pi-Star MMDVMHost binary and configuration on R1.
# Used when the custom build fails to start, crashes, breaks the USRP link or
# upsets an existing mode.

set -u

BACKUP=${BACKUP:-/root/r1-backup}
STORE=/usr/local/etc/r1-tail-elim

if [ ! -f "$BACKUP/MMDVMHost.orig" ]; then
    echo "no backup in $BACKUP, cannot roll back" >&2
    exit 1
fi

remount_ro=0
if mount | grep -qE "^/dev/.* on / type ext4 \(ro"; then
    remount_ro=1
    mount -o remount,rw / >/dev/null 2>&1
fi

systemctl disable --now r1-tail-elim-verify.timer >/dev/null 2>&1

cp -f "$BACKUP/MMDVMHost.orig" /usr/local/bin/MMDVMHost
chmod 755 /usr/local/bin/MMDVMHost
chown root:bin /usr/local/bin/MMDVMHost

if [ -f "$BACKUP/mmdvmhost.ini.orig" ]; then
    cp -f "$BACKUP/mmdvmhost.ini.orig" /etc/mmdvmhost
fi

echo "restarting mmdvmhost with the original binary"
systemctl restart mmdvmhost
sleep 8

if [ "$remount_ro" = "1" ]; then
    mount -o remount,ro / >/dev/null 2>&1
fi

echo "service: $(systemctl is-active mmdvmhost)"
/usr/local/bin/MMDVMHost --version
sha256sum /usr/local/bin/MMDVMHost
