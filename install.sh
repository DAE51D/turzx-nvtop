#!/usr/bin/env bash
# Install turzx-nvtop from this checkout.
#   ./install.sh                     user service (systemd --user), udev rule via sudo
#   sudo ./install.sh --system --run-as USER   system service for a headless host
# The service runs straight from this directory; keep the checkout where it is.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode=user; run_as=""
while [ $# -gt 0 ]; do
  case "$1" in
    --system) mode=system ;;
    --run-as) run_as="$2"; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
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

SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
echo "==> udev rule (stable /dev/turzx-lcd, keeps ModemManager away)"
$SUDO install -m 0644 "$here/packaging/99-turzx-lcd.rules" /etc/udev/rules.d/99-turzx-lcd.rules
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger --subsystem-match=tty --action=change || true

if [ "$mode" = user ]; then
  [ "$(id -u)" -ne 0 ] || { echo "run user mode without sudo" >&2; exit 1; }
  id -nG | tr ' ' '\n' | grep -qx dialout || echo "note: you are not in group 'dialout'; if /dev/turzx-lcd is not accessible run: sudo usermod -aG dialout $USER (then re-login)"
  cfg="$HOME/.config/turzx-nvtop"; mkdir -p "$cfg"
  [ -f "$cfg/config.ini" ] || cp "$here/config.example.ini" "$cfg/config.ini"
  unit="$HOME/.config/systemd/user"; mkdir -p "$unit"
  sed -e "s|@PYTHON@|$py|" -e "s|@DIR@|$here|" -e "s|@SYSTEM_ONLY@||" -e "s|@TARGET@|default.target|" \
    "$here/packaging/turzx-nvtop.service" > "$unit/turzx-nvtop.service"
  systemctl --user daemon-reload
  systemctl --user enable --now turzx-nvtop.service
  loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER" || echo "note: run 'sudo loginctl enable-linger $USER' to start at boot without a login"
  echo "Installed. Config: $cfg/config.ini   Logs: journalctl --user -u turzx-nvtop -f"
else
  [ "$(id -u)" -eq 0 ] || { echo "--system needs root" >&2; exit 1; }
  [ -n "$run_as" ] || { echo "--system needs --run-as USER (a user that may read /dev/turzx-lcd)" >&2; exit 1; }
  usermod -aG dialout "$run_as"
  mkdir -p /etc/turzx-nvtop
  [ -f /etc/turzx-nvtop/config.ini ] || cp "$here/config.example.ini" /etc/turzx-nvtop/config.ini
  sed -e "s|@PYTHON@|$py|" -e "s|@DIR@|$here|" -e "s|@SYSTEM_ONLY@|User=$run_as\nSupplementaryGroups=dialout|" -e "s|@TARGET@|multi-user.target|" \
    "$here/packaging/turzx-nvtop.service" > /etc/systemd/system/turzx-nvtop.service
  systemctl daemon-reload
  systemctl enable --now turzx-nvtop.service
  echo "Installed. Config: /etc/turzx-nvtop/config.ini   Logs: journalctl -u turzx-nvtop -f"
fi
