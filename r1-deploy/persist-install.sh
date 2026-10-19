#!/bin/bash
#
# Install the persistence helpers for the R1 tail elimination binary.
# Run as root from the checkout root or pass the binary path as $1.

set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
STORE=${STORE:-/usr/local/etc/r1-tail-elim}
BINARY=${1:-$SRC/../MMDVMHost}

[ -f "$BINARY" ] || { echo "binary not found: $BINARY" >&2; exit 1; }

mount -o remount,rw /

mkdir -p "$STORE"
cp -f "$BINARY" "$STORE/MMDVMHost.r1tail"
chmod 755 "$STORE/MMDVMHost.r1tail"
chown root:root "$STORE/MMDVMHost.r1tail"
sha256sum "$STORE/MMDVMHost.r1tail" | awk "{print \$1}" > "$STORE/MMDVMHost.sha256"
chmod 644 "$STORE/MMDVMHost.sha256"

sed "s|^STORE=.*|STORE=$STORE|" "$SRC/restore-binary.sh" > "$STORE/restore-binary.sh"
chmod 755 "$STORE/restore-binary.sh"
install -m 755 "$SRC/rollback.sh" "$STORE/rollback.sh"

# A post-merge hook restores the binary right after a Pi-Star git pull, before
# the daily cron starts the service again.
mkdir -p /usr/local/bin/.git/hooks
cat > /usr/local/bin/.git/hooks/post-merge <<HOOK
#!/bin/sh
$STORE/restore-binary.sh
HOOK
chmod 755 /usr/local/bin/.git/hooks/post-merge

# A cron entry re-checks the binary every 10 minutes. The systemd timer in
# this directory is kept for reference but cannot be used: the boxes only have
# about 16 MB free on /run, less than the systemd daemon-reload safety buffer,
# so any attempt to load a new unit fails.
CRON_NAME=$(basename "$STORE")
cat > "/etc/cron.d/$CRON_NAME" <<"CRON"
# Re-install the squelch tail elimination MMDVMHost binary if anything
# replaced it. Runs every 10 minutes, does nothing when the hash matches.
*/10 * * * * root $STORE/restore-binary.sh >/dev/null 2>&1
CRON
chmod 644 "/etc/cron.d/$CRON_NAME"

mount -o remount,ro /

echo "persistence helpers installed"
sha256sum "$STORE/MMDVMHost.r1tail" /usr/local/bin/MMDVMHost
