#!/bin/sh
# Install Keyboard Remapper system-wide.   sudo ./install.sh [PREFIX]      (default PREFIX=/usr/local)
# Needs: GTK 4 + libadwaita >= 1.0, python3, python3-evdev, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-gi-cairo
set -e
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
SRC=$(cd "$(dirname "$0")" && pwd)
LIB="$PREFIX/lib/keyboard-remapper"

install -d "$DESTDIR$LIB" "$DESTDIR$PREFIX/bin" "$DESTDIR$PREFIX/share/applications" \
  "$DESTDIR$PREFIX/share/icons/hicolor/scalable/apps" "$DESTDIR/etc/systemd/system" "$DESTDIR/etc/modules-load.d"
rm -rf "$DESTDIR$LIB/keyboard_remapper"
cp -r "$SRC/keyboard_remapper" "$DESTDIR$LIB/keyboard_remapper"
find "$DESTDIR$LIB" -name __pycache__ -prune -exec rm -rf {} +

for pair in "keyboard-remapperd:keyboard_remapper.daemon" "keyboard-remapper-ctl:keyboard_remapper.cli" "keyboard-remapper:keyboard_remapper.gui.app"; do
  name=${pair%%:*}; mod=${pair##*:}
  cat > "$DESTDIR$PREFIX/bin/$name" <<WRAP
#!/bin/sh
PYTHONPATH="$LIB\${PYTHONPATH:+:\$PYTHONPATH}" exec /usr/bin/python3 -c 'import sys; from $mod import main; sys.exit(main())' "\$@"
WRAP
  chmod 755 "$DESTDIR$PREFIX/bin/$name"
done

install -m 644 "$SRC/data/net.securejpn.Remapper.desktop" "$DESTDIR$PREFIX/share/applications/"
install -m 644 "$SRC/data/net.securejpn.Remapper.svg" "$DESTDIR$PREFIX/share/icons/hicolor/scalable/apps/"
install -m 644 "$SRC/data/keyboard-remapper-modules.conf" "$DESTDIR/etc/modules-load.d/keyboard-remapper.conf"
sed "s|@BINDIR@|$PREFIX/bin|" "$SRC/data/keyboard-remapperd.service" > "$DESTDIR/etc/systemd/system/keyboard-remapperd.service"

if [ -z "$DESTDIR" ]; then
  systemctl daemon-reload 2>/dev/null || true
  gtk-update-icon-cache -q "$PREFIX/share/icons/hicolor" 2>/dev/null || true
  echo "Installed. Start the background service with:"
  echo "  sudo systemctl enable --now keyboard-remapperd"
  echo "then launch 'Keyboard Remapper' from your application menu (or run keyboard-remapper)."
fi
