#!/usr/bin/env bash
# Proton Mail Bridge lifecycle inside the gateway container.
# Exposed as `protonctl` (symlinked in PATH). Usage:
#   protonctl login   # interactive: run via `docker exec -it`, then type `login`, do 2FA, `info`, `exit`
#   protonctl info    # show bridge IMAP/SMTP creds (after login)
#   protonctl run     # start the headless IMAP/SMTP servers (used by entrypoint)
set -e

DIR=/protonmail
export GNUPGHOME="${GNUPGHOME:-/data/bridge/gnupg}"
export PASSWORD_STORE_DIR="${PASSWORD_STORE_DIR:-/data/bridge/password-store}"

ensure_keychain() {
    mkdir -p "$GNUPGHOME" "$PASSWORD_STORE_DIR" \
        "${XDG_CONFIG_HOME:-/data/bridge/config}" \
        "${XDG_DATA_HOME:-/data/bridge/data}" \
        "${XDG_CACHE_HOME:-/data/bridge/cache}"
    chmod 700 "$GNUPGHOME"
    if [ ! -f "$PASSWORD_STORE_DIR/.gpg-id" ]; then
        echo "[protonctl] initializing pass/GPG keychain ..."
        gpg --generate-key --batch "$DIR/gpgparams"
        pass init pass-key
    fi
}

cmd="${1:-run}"; shift || true
case "$cmd" in
    login|info|init|"--cli")
        ensure_keychain
        # Interactive CLI — attach with `docker exec -it`.
        exec "$DIR/proton-bridge" --cli
        ;;
    run)
        ensure_keychain
        # Keep stdin open so the CLI-hosted IMAP/SMTP servers stay up (faketty trick).
        rm -f /tmp/faketty; mkfifo /tmp/faketty
        ( while true; do sleep 86400; done > /tmp/faketty ) &
        echo "[protonctl] starting Proton Bridge IMAP(1143)/SMTP(1025) ..."
        exec sh -c 'cat /tmp/faketty | "$0"/proton-bridge --cli' "$DIR"
        ;;
    *)
        ensure_keychain
        exec "$DIR/proton-bridge" --cli "$cmd" "$@"
        ;;
esac
