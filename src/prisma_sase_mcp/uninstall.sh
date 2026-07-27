#!/usr/bin/env bash
# Remove everything this project created OUTSIDE its own directory.
#
# Why this exists: uninstalling the Skill plugin, or deleting the Local MCP
# servers entry, leaves the artifacts in your HOME behind -- install.sh's
# ~100 MB virtualenv, the credential file, the launch log. No host uninstaller
# knows about those. A live removal session had to reverse-engineer the list.
# This script is that list, executable.
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

# Targets are collected in an ARRAY, never a space-joined string. With a
# string, `for t in $targets` word-splits on spaces, so a home directory like
# /Users/Eric Chen shattered every path -- and because `rm -rf` succeeds on a
# path that does not exist, the script printed "removed ..." for each fragment
# while the real credential file stayed on disk. A deletion tool reporting
# success while leaving a plaintext secret behind is the worst failure mode
# this script has, hence the array + the post-delete verification below.
# (Arrays are bash 3.2 / macOS-default safe; the ${a[@]+"${a[@]}"} idiom keeps
# an empty array from tripping `set -u`.)
targets=()
labels=()
_add() {
  [ -e "$1" ] || [ -L "$1" ] || return 0
  targets+=("$1")
  labels+=("${2:-}")
  echo "  - $1${2:+   ($2)}"
}

echo "Will remove:"
_add "$VENV" "virtualenv, typically ~100 MB"
_add "$LOG" "launch breadcrumb"

# Credential files: the canonical one AND look-alikes people create by hand
# (a live session found a stray ~/.prisma-sase2.env holding a plaintext
# secret at mode 644). List them all so none is silently left behind.
cred_files=()
for f in "$HOME"/.prisma-sase*.env; do
  [ -e "$f" ] || continue
  cred_files+=("$f")
done
if [ ${#cred_files[@]} -gt 0 ] && [ "$KEEP_CREDS" -eq 0 ]; then
  for f in "${cred_files[@]}"; do
    _add "$f" "CONTAINS CREDENTIALS"
  done
elif [ ${#cred_files[@]} -gt 0 ]; then
  echo ""
  echo "Keeping (--keep-credentials):"
  for f in "${cred_files[@]}"; do echo "  - $f"; done
fi

if [ ${#targets[@]} -eq 0 ]; then
  echo "  (nothing -- none of these exist)"
fi

echo ""
echo "NOT handled here (do these yourself -- they are not files in your HOME):"
echo "  1. The Local MCP servers entry named 'prisma-sase'. Settings >"
echo "     Extensions/Connectors > Local MCP servers > remove it. That entry"
echo "     holds PRISMA_CLIENT_ID / TSG / REGION in plaintext."
echo "  2. The Skill plugin, if you installed it:"
echo "       claude plugin uninstall prisma-sase@prisma-sase"
echo "       claude plugin marketplace remove prisma-sase"
echo "  3. The Client Secret in your OS keychain, if setup put it there:"
echo "       macOS: security delete-generic-password -s prisma-sase -a client_secret"
echo "       Linux: secret-tool clear service prisma-sase key client_secret"
echo "       pass:  pass rm prisma-sase/client_secret"

if [ "$DRY_RUN" -eq 1 ]; then
  echo ""
  echo "(--dry-run: nothing was deleted)"
  exit 0
fi
if [ ${#targets[@]} -eq 0 ]; then
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
# Verify each removal instead of trusting rm's exit status: `rm -rf` returns 0
# for a path that was never there, so "rm succeeded" does NOT mean "the file is
# gone" if the path was ever mangled. Check the filesystem and fail loudly.
failed=()
for t in "${targets[@]}"; do
  rm -rf "$t" || true
  if [ -e "$t" ] || [ -L "$t" ]; then
    failed+=("$t")
    echo "FAILED to remove $t" >&2
  else
    echo "removed $t"
  fi
done

if [ ${#failed[@]} -gt 0 ]; then
  echo "" >&2
  echo "ERROR: ${#failed[@]} item(s) could not be removed (listed above)." >&2
  echo "  Check permissions and delete them by hand. If a credential file is" >&2
  echo "  among them, treat the secret as still on disk." >&2
  exit 1
fi

echo ""
echo "== done =="
if [ "$KEEP_CREDS" -eq 0 ] && [ ${#cred_files[@]} -gt 0 ]; then
  echo "A credential file was deleted. If that secret was ever stored in"
  echo "plaintext or with loose permissions, ROTATE it in Strata Cloud Manager"
  echo "(IAM > the service account > regenerate the client secret) -- deleting"
  echo "the file does not undo the exposure."
fi
