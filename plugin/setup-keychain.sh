#!/usr/bin/env bash
# Store the Client Secret in your OS keychain, and write a NON-SENSITIVE
# ~/.prisma-sase.env that fetches it from there at startup.
#
# When to use this
# ----------------
# The plugin's enable dialog is the recommended path: it puts the secret in
# secure storage for you. Use this script when the dialog is not available or
# did not run -- most notably the host bug where a plugin is enabled without
# ever being asked for its configuration (see the plugin README, "When the
# enable dialog never asked for anything"). Also useful for CI-ish setups and
# anyone who wants the env-file fallback without a plaintext secret on disk.
#
# What it does
# ------------
#   1. Stores the Client Secret in: macOS Keychain / secret-tool / pass.
#      It is read from a hidden prompt or stdin -- never a command-line
#      argument (arguments are visible in `ps` to every process on the box).
#   2. Writes ~/.prisma-sase.env with the three NON-secret values plus a
#      PRISMA_SECRET_CMD line that fetches the secret on each server start.
#      The file itself then contains nothing sensitive.
#   3. Verifies by running the fetch command back.
#
# Usage:
#   bash setup-keychain.sh                 # prompts for everything
#   bash setup-keychain.sh --show          # print what is stored, change nothing
#   bash setup-keychain.sh --remove        # delete the keychain entry
#   printf '%s' "$SECRET" | bash setup-keychain.sh --stdin   # non-interactive
#
# Written for bash 3.2 (macOS default).
set -eu

SERVICE="prisma-sase"
ACCOUNT="client_secret"
ENVF="${PRISMA_ENV_FILE:-$HOME/.prisma-sase.env}"

MODE="setup"
FROM_STDIN=0
for arg in "$@"; do
  case "$arg" in
    --show)   MODE="show" ;;
    --remove) MODE="remove" ;;
    --stdin)  FROM_STDIN=1 ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# --- pick a secret backend ----------------------------------------------------
# Order matches the platform's native store first. Each backend defines how to
# store, fetch and delete; the fetch command is what lands in the env file.
BACKEND=""
if [ "$(uname -s)" = "Darwin" ] && command -v security >/dev/null 2>&1; then
  BACKEND="keychain"
  FETCH_CMD="security find-generic-password -s $SERVICE -a $ACCOUNT -w"
elif command -v secret-tool >/dev/null 2>&1; then
  BACKEND="secret-tool"
  FETCH_CMD="secret-tool lookup service $SERVICE key $ACCOUNT"
elif command -v pass >/dev/null 2>&1; then
  BACKEND="pass"
  FETCH_CMD="pass show $SERVICE/$ACCOUNT"
else
  echo "ERROR: no supported secret store found." >&2
  echo "  macOS : 'security' is built in -- this should not happen." >&2
  echo "  Linux : sudo apt install libsecret-tools   (provides secret-tool)" >&2
  echo "          or: sudo apt install pass" >&2
  echo "  Other : store the secret yourself and set PRISMA_SECRET_CMD in" >&2
  echo "          $ENVF to any command that prints it on stdout." >&2
  exit 1
fi

_fetch() { eval "$FETCH_CMD" 2>/dev/null; }

_store() {   # $1 = the secret, read from stdin by the caller
  case "$BACKEND" in
    keychain)
      # -U updates an existing entry instead of erroring on duplicate.
      security add-generic-password -s "$SERVICE" -a "$ACCOUNT" -U -w "$1"
      ;;
    secret-tool)
      printf '%s' "$1" | secret-tool store --label="Prisma SASE client secret" \
        service "$SERVICE" key "$ACCOUNT"
      ;;
    pass)
      printf '%s\n' "$1" | pass insert -m -f "$SERVICE/$ACCOUNT" >/dev/null
      ;;
  esac
}

_remove() {
  case "$BACKEND" in
    keychain)    security delete-generic-password -s "$SERVICE" -a "$ACCOUNT" >/dev/null 2>&1 ;;
    secret-tool) secret-tool clear service "$SERVICE" key "$ACCOUNT" >/dev/null 2>&1 ;;
    pass)        pass rm -f "$SERVICE/$ACCOUNT" >/dev/null 2>&1 ;;
  esac
}

echo "== prisma-sase keychain setup =="
echo "-- backend: $BACKEND"
echo ""

# --- --show -------------------------------------------------------------------
if [ "$MODE" = "show" ]; then
  if _fetch >/dev/null 2>&1 && [ -n "$(_fetch)" ]; then
    echo "secret     : STORED in $BACKEND (value not printed)"
  else
    echo "secret     : not stored"
  fi
  echo "fetch cmd  : $FETCH_CMD"
  if [ -f "$ENVF" ]; then
    echo "env file   : $ENVF (mode $(ls -l "$ENVF" | cut -c2-10))"
    if grep -q '^PRISMA_SECRET_CMD=' "$ENVF" 2>/dev/null; then
      echo "             uses PRISMA_SECRET_CMD -- no plaintext secret"
    elif grep -q '^PRISMA_CLIENT_SECRET=.\+' "$ENVF" 2>/dev/null; then
      echo "             WARNING: contains a PLAINTEXT PRISMA_CLIENT_SECRET"
    fi
  else
    echo "env file   : $ENVF does not exist"
  fi
  exit 0
fi

# --- --remove -----------------------------------------------------------------
if [ "$MODE" = "remove" ]; then
  _remove
  echo "-- removed the $BACKEND entry for $SERVICE/$ACCOUNT (if it existed)"
  echo ""
  echo "NOTE: $ENVF was left alone. If it still has a PRISMA_SECRET_CMD line,"
  echo "      the server will now find no secret. Remove that line, or re-run"
  echo "      this script to store one again."
  exit 0
fi

# --- setup --------------------------------------------------------------------
# The secret: hidden prompt, or stdin for non-interactive use. Never an argv.
if [ "$FROM_STDIN" -eq 1 ]; then
  SECRET="$(cat)"
else
  printf "Client Secret (input hidden): "
  stty -echo 2>/dev/null || true
  read -r SECRET < /dev/tty
  stty echo 2>/dev/null || true
  printf "\n"
fi
if [ -z "$SECRET" ]; then
  echo "ERROR: empty secret -- nothing stored." >&2
  exit 1
fi

_store "$SECRET"
SECRET=""            # drop it from this shell's memory immediately
echo "-- stored in $BACKEND"

# Verify by reading it back: a store that cannot be read is worse than none,
# because the failure would surface later as an auth error.
if [ -z "$(_fetch)" ]; then
  echo "ERROR: stored, but reading it back returned nothing." >&2
  echo "  Try by hand: $FETCH_CMD" >&2
  exit 1
fi
echo "-- verified: the fetch command returns a value"

# The three non-secret values. Keep whatever the file already has.
_existing() { [ -f "$ENVF" ] && grep "^$1=" "$ENVF" 2>/dev/null | head -1 | cut -d= -f2- || true; }
CID="$(_existing PRISMA_CLIENT_ID)"
TSG="$(_existing PRISMA_TSG_ID)"
REG="$(_existing PRISMA_REGION)"

if [ "$FROM_STDIN" -eq 0 ]; then
  echo ""
  echo "The other three values are NOT secret and go in $ENVF."
  echo "Press Enter to keep the current value shown in brackets."
  printf "Client ID [%s]: " "${CID:-empty}"; read -r ans < /dev/tty; [ -n "$ans" ] && CID="$ans"
  printf "TSG ID    [%s]: " "${TSG:-empty}"; read -r ans < /dev/tty; [ -n "$ans" ] && TSG="$ans"
  printf "Region    [%s]: " "${REG:-sg}";    read -r ans < /dev/tty; [ -n "$ans" ] && REG="$ans"
fi
# Region has a sane default; the other two genuinely have to come from the
# user, so an unattended run that leaves them blank must SAY so rather than
# write a file that looks complete and fails at the first API call.
[ -z "$REG" ] && REG="sg"
INCOMPLETE=""
[ -z "$CID" ] && INCOMPLETE="$INCOMPLETE PRISMA_CLIENT_ID"
[ -z "$TSG" ] && INCOMPLETE="$INCOMPLETE PRISMA_TSG_ID"

# Preserve any tuning variables already in the file (PRISMA_INSIGHTS_MAP etc.)
# -- the enable dialog does not cover those, so this file is their only home.
PRESERVED=""
HAD_PLAINTEXT=0
if [ -f "$ENVF" ]; then
  PRESERVED="$(grep -E '^PRISMA_(INSIGHTS_MAP|FILTER_|ADEM_|SUBTENANT_ID|HTTP_TIMEOUT|MOCK|PYTHON)' "$ENVF" 2>/dev/null || true)"
  # A plaintext secret is about to be replaced by the PRISMA_SECRET_CMD line.
  # Deleting the line does not un-expose the value -- it may be in backups,
  # Time Machine, or a synced folder -- so this has to be said out loud.
  if grep -qE '^PRISMA_CLIENT_SECRET=.+' "$ENVF" 2>/dev/null; then
    HAD_PLAINTEXT=1
  fi
fi

TMP="$ENVF.tmp.$$"
{
  echo "# prisma-sase credentials -- written by setup-keychain.sh"
  echo "#"
  echo "# The Client Secret is NOT in this file. It lives in your $BACKEND and"
  echo "# is fetched at server start by the PRISMA_SECRET_CMD line below, so"
  echo "# this file contains nothing sensitive."
  echo "#"
  echo "# The plugin's enable dialog remains the recommended path when it works"
  echo "# -- it needs no file at all. This file is the fallback, and it also"
  echo "# holds the tuning variables the dialog does not cover."
  echo "PRISMA_CLIENT_ID=$CID"
  echo "PRISMA_TSG_ID=$TSG"
  echo "PRISMA_REGION=$REG"
  echo "PRISMA_SECRET_CMD=$FETCH_CMD"
  if [ -n "$PRESERVED" ]; then
    echo ""
    echo "# --- preserved from the previous file ---"
    echo "$PRESERVED"
  fi
} > "$TMP"
mv "$TMP" "$ENVF"
chmod 600 "$ENVF"
echo "-- wrote $ENVF (chmod 600, no secret inside)"

if [ "$HAD_PLAINTEXT" -eq 1 ]; then
  echo ""
  echo "!! $ENVF previously held a PLAINTEXT Client Secret. That line is gone"
  echo "   now, but deleting it does not undo the exposure -- the value may"
  echo "   survive in backups, Time Machine, or a synced folder."
  echo "   ROTATE the secret in Strata Cloud Manager (IAM > the service"
  echo "   account > regenerate), then re-run this script with the new one."
fi

if [ -n "$INCOMPLETE" ]; then
  echo ""
  echo "WARNING: still empty in $ENVF:$INCOMPLETE" >&2
  echo "  The secret is stored, but the server needs all four values." >&2
  echo "  Fill those lines in (they are not secret), or re-run this script" >&2
  echo "  interactively: bash setup-keychain.sh" >&2
fi

echo ""
echo "== done =="
echo "Verify:  ~/.prisma-sase-venv/bin/python <plugin>/mcp/server.py --selfcheck"
echo "         (expect: secret from: PRISMA_SECRET_CMD (keychain/manager-backed))"
echo "Then RESTART the app completely -- Desktop: Cmd-Q; CLI: /reload-plugins."
echo ""
echo "If the enable dialog starts working later, it takes precedence"
echo "automatically -- host-provided values win over this file. At that point"
echo "you can delete the three credential lines here (keep any tuning ones)."
