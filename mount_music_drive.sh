#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "$0")
DEFAULT_FINAL_MOUNT=/srv/music
DEFAULT_SOURCE_MOUNT=/mnt/musicdrive
FSTAB_FILE=/etc/fstab
BEGIN_MARK="# BEGIN musicplayer managed mount"
END_MARK="# END musicplayer managed mount"

log() {
  printf '[%s] %s\n' "$SCRIPT_NAME" "$*"
}

fail() {
  printf '[%s] ERROR: %s\n' "$SCRIPT_NAME" "$*" >&2
  exit 1
}

require_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    log "Re-running with sudo..."
    exec sudo bash "$0" "$@"
  fi
}

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--device /dev/sdX1] [--mode direct|bind] [--yes]

This helper will:
  1. Show attached drives/partitions
  2. Let you pick a USB partition
  3. Add persistent /etc/fstab entries by UUID
  4. Make the music available at $DEFAULT_FINAL_MOUNT

Modes:
  direct  Mount the USB partition directly at $DEFAULT_FINAL_MOUNT
  bind    Mount the USB partition at $DEFAULT_SOURCE_MOUNT, then bind-mount it to $DEFAULT_FINAL_MOUNT

Why bind instead of symlink?
  MPD works more reliably with real mounts than symlinks, so this script uses
  a bind mount instead of a symlink when you want a separate underlying mountpoint.
EOF
}

DEVICE=""
MODE="direct"
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      DEVICE=${2:-}
      shift 2
      ;;
    --mode)
      MODE=${2:-}
      shift 2
      ;;
    --yes|-y)
      ASSUME_YES=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ "$MODE" == "direct" || "$MODE" == "bind" ]] || fail "--mode must be 'direct' or 'bind'"

confirm() {
  local prompt=$1
  if [[ $ASSUME_YES -eq 1 ]]; then
    return 0
  fi
  read -r -p "$prompt [y/N]: " answer
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

pick_device() {
  log "Detected block devices:"
  lsblk -o NAME,PATH,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINT,MODEL,TRAN | sed 's/^/  /'
  echo
  read -r -p "Enter the partition to use for music (example: /dev/sda1): " DEVICE
}

get_field() {
  local field=$1
  local dev=$2
  lsblk -no "$field" "$dev" | head -n1 | tr -d ' '
}

safe_backup_dir() {
  local path=$1
  local backup="${path}.pre-usb-mount.$(date +%Y%m%d-%H%M%S)"
  mv "$path" "$backup"
  mkdir -p "$path"
  log "Backed up existing contents to: $backup"
}

ensure_empty_mountpoint() {
  local path=$1
  if [[ -L "$path" ]]; then
    fail "$path is a symlink. Remove it first, then re-run this script."
  fi

  mkdir -p "$path"

  if mountpoint -q "$path"; then
    fail "$path is already a mountpoint. Unmount it first if you want to change it."
  fi

  if [[ -n "$(find "$path" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    log "$path is not empty."
    confirm "Back it up and continue?" || fail "Aborted."
    safe_backup_dir "$path"
  fi
}

update_fstab() {
  local block=$1
  local tmp
  tmp=$(mktemp)

  awk -v begin="$BEGIN_MARK" -v end="$END_MARK" '
    $0 == begin { skipping=1; next }
    $0 == end { skipping=0; next }
    skipping != 1 { print }
  ' "$FSTAB_FILE" > "$tmp"

  {
    cat "$tmp"
    echo
    echo "$BEGIN_MARK"
    printf '%s\n' "$block"
    echo "$END_MARK"
  } > "$FSTAB_FILE"

  rm -f "$tmp"
}

main() {
  require_root "$@"

  command -v lsblk >/dev/null || fail "lsblk not found"
  command -v blkid >/dev/null || fail "blkid not found"
  command -v mountpoint >/dev/null || fail "mountpoint not found"

  if [[ -z "$DEVICE" ]]; then
    pick_device
  fi

  [[ -b "$DEVICE" ]] || fail "$DEVICE is not a block device"

  local uuid fstype opts music_uid music_gid source_mount final_mount fstab_block
  uuid=$(blkid -s UUID -o value "$DEVICE" || true)
  fstype=$(blkid -s TYPE -o value "$DEVICE" || true)
  [[ -n "$uuid" ]] || fail "Could not read UUID from $DEVICE"
  [[ -n "$fstype" ]] || fail "Could not read filesystem type from $DEVICE. Is it formatted?"

  music_uid=$(id -u pi)
  music_gid=$(id -g pi)
  final_mount=$DEFAULT_FINAL_MOUNT
  source_mount=$DEFAULT_SOURCE_MOUNT

  case "$fstype" in
    exfat|vfat|fat|msdos)
      opts="defaults,nofail,uid=$music_uid,gid=$music_gid,umask=0022,x-systemd.device-timeout=10"
      ;;
    ntfs|ntfs3)
      opts="defaults,nofail,uid=$music_uid,gid=$music_gid,umask=0022,x-systemd.device-timeout=10"
      ;;
    ext2|ext3|ext4|xfs|btrfs)
      opts="defaults,nofail,x-systemd.device-timeout=10"
      ;;
    *)
      log "Filesystem '$fstype' is not specially handled; using generic defaults."
      opts="defaults,nofail,x-systemd.device-timeout=10"
      ;;
  esac

  log "Selected device: $DEVICE"
  log "UUID: $uuid"
  log "Filesystem: $fstype"
  log "Mode: $MODE"

  if [[ "$MODE" == "direct" ]]; then
    ensure_empty_mountpoint "$final_mount"
    fstab_block="UUID=$uuid  $final_mount  $fstype  $opts  0  2"
  else
    ensure_empty_mountpoint "$source_mount"
    ensure_empty_mountpoint "$final_mount"
    fstab_block=$(cat <<EOF
UUID=$uuid  $source_mount  $fstype  $opts  0  2
$source_mount  $final_mount  none  bind,nofail  0  0
EOF
)
  fi

  log "About to write persistent mount settings to $FSTAB_FILE"
  echo
  echo "$BEGIN_MARK"
  printf '%s\n' "$fstab_block"
  echo "$END_MARK"
  echo
  confirm "Apply these changes?" || fail "Aborted."

  update_fstab "$fstab_block"

  mkdir -p "$final_mount"
  [[ "$MODE" == "bind" ]] && mkdir -p "$source_mount"

  log "Running: mount -a"
  mount -a

  log "Done. Current mounts involving music:"
  findmnt | grep -E '(/srv/music|/mnt/musicdrive)' || true
  echo
  log "You can now copy music into $DEFAULT_FINAL_MOUNT"
}

main "$@"
