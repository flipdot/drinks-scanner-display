#!/bin/bash

KEYS=(
    -r B04800CE
    -r 08B0AE86
    -r 99CABD50
)
MAIL=(
    vorstand@flipdot.org
    c+drinks@cfs.im
)
export FROM=flipdot-noti@vega.uberspace.de
SUBJECT="Drinks Report"

tmp=$(mktemp)
function send_cleanup() {
    gpg -ea "${KEYS[@]}" --always-trust -o - < "$tmp" \
        | mailx -r "$FROM" -s "$SUBJECT" "${MAIL[@]}"
    rm -f "$tmp"*
}
trap send_cleanup EXIT TERM INT

if ! python pullLdapUsersToDatabase.py > "$tmp.ldap" 2>&1; then
    cat "$tmp.ldap" >> "$tmp"
    exit
fi

sudo -u postgres psql drinks < docs/auflandungs_stats.sql |head -n10 >> "$tmp"
