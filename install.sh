#!/usr/bin/env bash
# Install turzx-nvtop from this checkout.
#   ./install.sh                     user service (systemd --user), udev rule via sudo
#   sudo ./install.sh --system --run-as USER   system service for a headless host
#   ./install.sh --udev-only         just the udev rule (device access + ModemManager ignore)
# The service runs straight from this directory; keep the checkout where it is.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode=user; run_as=""; udev_only=0
while [ $# -gt 0 ]; do
  case "$1" in
    --system) mode=system ;;
    --udev-only) udev_only=1 ;;
    --run-as) run_as="$2"; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac; shift
done

py="$(command -v python3)" || { echo "python3 not found" >&2; exit 1; }
if ! "$py" -c 'import PIL, numpy' 2>/dev/null; then
  cat >&2 <<MSG
Missing Pillow and/or numpy for $py. Install one of:
  Debian/Ubuntu: sudo apt install python3-pil python3-numpy
  Fedora:        sudo dnf install python3-pillow python3-numpy
  Arch:          sudo pacman -S python-pillow python-numpy
  any:           python3 -m pip install --user pillow numpy
MSG
  exit 1
fi


# The one dependency this script cannot install: nvstats-service with its HTTP API.
check_nvstats() {
  if (cd "$here" && "$py" -c 'import urllib.request as u; from turzx_nvtop.config import Config; c = Config(None); u.urlopen(c.s("nvstats", "url").rstrip("/") + "/health", timeout=3)') 2>/dev/null; then
    echo "nvstats-service is reachable."
  else
    cat <<MSG
WARNING: nvstats-service is not answering at the configured URL (default http://127.0.0.1:8039), so the
display will show NO DATA until it is. Install it (https://github.com/DAE51D/nvstats-service) with HTTP enabled:
  git clone https://github.com/DAE51D/nvstats-service.git && cd nvstats-service && ./install.sh --http
MSG
  fi
}

SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
# Serial-port group differs by distro: dialout (Debian, Ubuntu, Fedora, ...) or uucp (Arch, ...).
grp=""
for g in dialout uucp; do getent group "$g" >/dev/null && { grp="$g"; break; }; done
echo "==> udev rule (stable /dev/turzx-lcd, uaccess for the logged-in user, keeps ModemManager away)"
rule=/etc/udev/rules.d/70-turzx-lcd.rules
$SUDO rm -f /etc/udev/rules.d/99-turzx-lcd.rules      # earlier releases used a name that sorted too late to work
if [ -n "$grp" ]; then sed "s|@GROUP@|$grp|" "$here/packaging/70-turzx-lcd.rules"
else sed 's|GROUP="@GROUP@", ||' "$here/packaging/70-turzx-lcd.rules"; fi | $SUDO tee "$rule" >/dev/null
$SUDO chmod 0644 "$rule"
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger --subsystem-match=tty --action=add || true
if [ "$udev_only" = 1 ]; then echo "udev rule installed ($rule). Re-plug the display if it was already connected."; exit 0; fi

echo "==> sleep hook (blanks the display on suspend/hibernate: a powered idle panel burns in)"
# a copy, root-owned: systemd runs it as root, so it must never be a symlink into a user-writable directory
$SUDO install -D -m 0755 -o root -g root "$here/packaging/turzx-nvtop-sleep" /usr/lib/systemd/system-sleep/turzx-nvtop

if [ "$mode" = user ]; then
  [ "$(id -u)" -ne 0 ] || { echo "run user mode without sudo" >&2; exit 1; }
  [ -w /dev/turzx-lcd ] 2>/dev/null || echo "note: /dev/turzx-lcd is not writable for you yet. Re-plug the display; on a headless box (no local login) add yourself to '${grp:-dialout}': sudo usermod -aG ${grp:-dialout} $USER, then log in again"
  cfg="$HOME/.config/turzx-nvtop"; mkdir -p "$cfg"
  [ -f "$cfg/config.ini" ] || cp "$here/config.example.ini" "$cfg/config.ini"
  unit="$HOME/.config/systemd/user"; mkdir -p "$unit"
  sed -e "s|@PYTHON@|$py|" -e "s|@DIR@|$here|" -e "s|@SYSTEM_ONLY@||" -e "s|@TARGET@|default.target|" \
    "$here/packaging/turzx-nvtop.service" > "$unit/turzx-nvtop.service"
  systemctl --user daemon-reload
  systemctl --user enable --now turzx-nvtop.service
  loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER" || echo "note: run 'sudo loginctl enable-linger $USER' to start at boot without a login"
  echo "Installed. Config: $cfg/config.ini   Logs: journalctl --user -u turzx-nvtop -f"
  check_nvstats
else
  [ "$(id -u)" -eq 0 ] || { echo "--system needs root" >&2; exit 1; }
  [ -n "$run_as" ] || { echo "--system needs --run-as USER (a user that may read /dev/turzx-lcd)" >&2; exit 1; }
  [ -n "$grp" ] && usermod -aG "$grp" "$run_as"
  mkdir -p /etc/turzx-nvtop
  [ -f /etc/turzx-nvtop/config.ini ] || cp "$here/config.example.ini" /etc/turzx-nvtop/config.ini
  sed -e "s|@PYTHON@|$py|" -e "s|@DIR@|$here|" -e "s|@SYSTEM_ONLY@|User=$run_as\nSupplementaryGroups=${grp:-dialout}\nRuntimeDirectory=turzx-nvtop|" -e "s|@TARGET@|multi-user.target|" \
    "$here/packaging/turzx-nvtop.service" > /etc/systemd/system/turzx-nvtop.service
  systemctl daemon-reload
  systemctl enable --now turzx-nvtop.service
  echo "Installed. Config: /etc/turzx-nvtop/config.ini   Logs: journalctl -u turzx-nvtop -f"
  check_nvstats
fi
