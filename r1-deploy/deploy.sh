#!/bin/bash
#
# Deploy the R1 squelch tail elimination MMDVMHost build.
# Any failed health check triggers an automatic rollback to the original
# Pi-Star binary and configuration.

set -u

SRC=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SRC/.." && pwd)
BINARY=${1:-$ROOT/MMDVMHost}
BACKUP=${BACKUP:-/root/r1-backup}
INI=/etc/mmdvmhost
AUDITLOG=/var/log/r1-tail-elim.log
TODAY=$(date -u +%F)
MMDVM_LOG=/var/log/pi-star/MMDVM-$TODAY.log
USRP_PORT=$(awk -F= "/^\[FM Network\]/{f=1} f&&/^LocalPort=/{print \$2; exit}" "$INI" 2>/dev/null | tr -d " \r")

say() { echo "[deploy] $*"; echo "$(date -Is) deploy: $*" >> "$AUDITLOG" 2>/dev/null; }

fail() {
    echo "[deploy] FAILED: $*"
    echo "$(date -Is) deploy failed: $*" >> "$AUDITLOG" 2>/dev/null
    "$SRC/rollback.sh"
    exit 1
}

[ -f "$BINARY" ] || fail "binary $BINARY is missing"
[ -f "$BACKUP/MMDVMHost.orig" ] || fail "no backup in $BACKUP"
[ -f "$BACKUP/mmdvmhost.ini.orig" ] || fail "no ini backup in $BACKUP"
[ -n "$USRP_PORT" ] || fail "cannot read the FM Network LocalPort from $INI"

say "installing $BINARY"
mount -o remount,rw / || fail "cannot remount / read write"
cp -f "$BINARY" /usr/local/bin/MMDVMHost || fail "cannot copy the binary"
chmod 755 /usr/local/bin/MMDVMHost
chown root:bin /usr/local/bin/MMDVMHost

python3 - "$INI" <<"PY" || fail "cannot update $INI"
import sys
path = sys.argv[1]
text = open(path).read()
if "SquelchTailElim=" not in text:
    if "[FM Network]" not in text:
        sys.exit(2)
    text = text.replace("[FM Network]\n",
                        "[FM Network]\nSquelchTailElim=1\nSquelchTailElimMs=200\n", 1)
    open(path, "w").write(text)
PY

say "restarting mmdvmhost"
systemctl restart mmdvmhost
sleep 12
mount -o remount,ro /

systemctl is-active --quiet mmdvmhost || fail "mmdvmhost is not active after restart"

grep -q "Squelch Tail Elim: yes" "$MMDVM_LOG" || fail "tail elimination not enabled in the log"
grep -q "Squelch Tail Elim Delay: 200ms" "$MMDVM_LOG" || fail "delay not reported in the log"
grep -q "Opening UDP port on $USRP_PORT" "$MMDVM_LOG" || fail "USRP uplink socket $USRP_PORT not opened"
grep -q "is running" "$MMDVM_LOG" || fail "MMDVMHost did not report running"

say "waiting 30 s for stability"
sleep 30
systemctl is-active --quiet mmdvmhost || fail "mmdvmhost died during the stability window"
grep -q "Squelch Tail Elim: yes" "$MMDVM_LOG" || fail "tail elimination disappeared from the log"

if ss -lunp 2>/dev/null | grep -q ":$USRP_PORT"; then
    say "USRP socket $USRP_PORT is bound"
else
    fail "USRP socket $USRP_PORT is not bound"
fi

say "deployment successful"
/usr/local/bin/MMDVMHost --version
sha256sum /usr/local/bin/MMDVMHost
