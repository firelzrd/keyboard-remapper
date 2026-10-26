#!/bin/sh
# sudo ./uninstall.sh [PREFIX]
PREFIX=${1:-/usr/local}
DESTDIR=${DESTDIR:-}
# System-wide install needs root (not when staging into a DESTDIR): re-run through sudo.
if [ -z "$DESTDIR" ] && [ "$(id -u)" != 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "Root privileges are needed - running again with sudo..."
    exec sudo "$0" "$@"
  fi
  echo "Please run this script as root:  su -c '$0 $*'" >&2
  exit 1
fi
systemctl disable --now keyboard-remapperd 2>/dev/null || true
rm -rf "$PREFIX/lib/keyboard-remapper" "$PREFIX/bin/keyboard-remapperd" "$PREFIX/bin/keyboard-remapper-ctl" "$PREFIX/bin/keyboard-remapper" \
  "$PREFIX/share/applications/net.securejpn.Remapper.desktop" \
  "$PREFIX/share/icons/hicolor/scalable/apps/net.securejpn.Remapper.svg" \
  /etc/systemd/system/keyboard-remapperd.service /etc/modules-load.d/keyboard-remapper.conf
systemctl daemon-reload 2>/dev/null || true
echo "Removed. Your presets in ~/.config/keyboard-remapper and /var/lib/keyboard-remapper were kept."
