#!/bin/bash
#
# Install the persistence helpers for the R1 tail elimination binary.
# Run as root from the checkout root or pass the binary path as $1.

set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
STORE=/usr/local/etc/r1-tail-elim
BINARY=${1:-$SRC/../MMDVMHost}

[ -f "$BINARY" ] || { echo "binary not found: $BINARY" >&2; exit 1; }

mount -o remount,rw /

mkdir -p "$STORE"
cp -f "$BINARY" "$STORE/MMDVMHost.r1tail"
chmod 755 "$STORE/MMDVMHost.r1tail"
chown root:root "$STORE/MMDVMHost.r1tail"
sha256sum "$STORE/MMDVMHost.r1tail" | awk "{print \$1}" > "$STORE/MMDVMHost.sha256"
chmod 644 "$STORE/MMDVMHost.sha256"

install -m 755 "$SRC/restore-binary.sh" "$STORE/restore-binary.sh"
install -m 755 "$SRC/rollback.sh" "$STORE/rollback.sh"

# A post-merge hook restores the binary right after a Pi-Star git pull, before
# the daily cron starts the service again.
mkdir -p /usr/local/bin/.git/hooks
cat > /usr/local/bin/.git/hooks/post-merge <<"HOOK"
#!/bin/sh
/usr/local/etc/r1-tail-elim/restore-binary.sh
HOOK
chmod 755 /usr/local/bin/.git/hooks/post-merge

install -m 644 "$SRC/r1-tail-elim-verify.service" /etc/systemd/system/
install -m 644 "$SRC/r1-tail-elim-verify.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now r1-tail-elim-verify.timer

mount -o remount,ro /

echo "persistence helpers installed"
sha256sum "$STORE/MMDVMHost.r1tail" /usr/local/bin/MMDVMHost
