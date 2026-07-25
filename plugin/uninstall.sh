#!/usr/bin/env bash
# Remove everything this plugin created OUTSIDE its own directory.
#
# Why this exists: `claude plugin uninstall` removes the plugin tree, its
# registry entries and its data dir -- but install.sh deliberately creates
# artifacts in your HOME (a ~100 MB virtualenv, a credential file, a launch
# log) that no host uninstaller knows about. A live removal session had to
# reverse-engineer that list. This script is that list, executable.
#
# Usage:
#   bash uninstall.sh              # show the plan, then ask before deleting
#   bash uninstall.sh --yes        # no prompt
#   bash uninstall.sh --keep-credentials   # leave the env file(s) alone
#   bash uninstall.sh --dry-run    # only show what would be removed
set -eu

ASSUME_YES=0
KEEP_CREDS=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --keep-credentials) KEEP_CREDS=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

VENV="${PRISMA_VENV:-$HOME/.prisma-sase-venv}"
LOG="$HOME/.prisma-sase-launch.log"

echo "== prisma-sase uninstall =="
echo ""

targets=""
_add() { [ -e "$1" ] || [ -L "$1" ] || return 0; targets="$targets $1"; echo "  - $1${2:+   ($2)}"; }

echo "Will remove:"
_add "$VENV" "virtualenv, typically ~100 MB"
_add "$LOG" "launch breadcrumb"

# Credential files: the canonical one AND look-alikes people create by hand
# (a live session found a stray ~/.prisma-sase2.env holding a plaintext
# secret at mode 644). List them all so none is silently left behind.
cred_files=""
for f in "$HOME"/.prisma-sase*.env; do
  [ -e "$f" ] || continue
  cred_files="$cred_files $f"
done
if [ -n "$cred_files" ] && [ "$KEEP_CREDS" -eq 0 ]; then
  for f in $cred_files; do
    _add "$f" "CONTAINS CREDENTIALS"
  done
elif [ -n "$cred_files" ]; then
  echo ""
  echo "Keeping (--keep-credentials):"
  for f in $cred_files; do echo "  - $f"; done
fi

if [ -z "$targets" ]; then
  echo "  (nothing -- none of these exist)"
fi

echo ""
echo "NOT handled here (run these yourself -- they are the host's to remove):"
echo "  claude plugin uninstall prisma-sase-mac@prisma-sase   # or -linux / -windows"
echo "  claude plugin marketplace remove prisma-sase"
echo "  (Claude Desktop: Settings > Plugins > uninstall, then remove the marketplace)"
echo "  Those clear the plugin tree, installed_plugins.json, enabledPlugins and"
echo "  pluginConfigs -- including the Client Secret held in OS secure storage."

if [ "$DRY_RUN" -eq 1 ]; then
  echo ""
  echo "(--dry-run: nothing was deleted)"
  exit 0
fi
if [ -z "$targets" ]; then
  exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  echo ""
  printf "Delete the items above? [y/N] "
  read -r reply < /dev/tty || reply=""
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "Aborted -- nothing deleted."; exit 0 ;;
  esac
fi

echo ""
for t in $targets; do
  rm -rf "$t" && echo "removed $t"
done

echo ""
echo "== done =="
if [ "$KEEP_CREDS" -eq 0 ] && [ -n "$cred_files" ]; then
  echo "A credential file was deleted. If that secret was ever stored in"
  echo "plaintext or with loose permissions, ROTATE it in Strata Cloud Manager"
  echo "(IAM > the service account > regenerate the client secret) -- deleting"
  echo "the file does not undo the exposure."
fi
