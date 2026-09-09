#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: $0 HOSTNAME IP_ADDRESS" >&2
    exit 2
fi

hostname="$1"
ip_address="$2"
workdir="$(dirname "$0")"

sed \
    -e "s/YOUR_SERVER_HOSTNAME_OR_IP/${hostname}/g" \
    -e "s/YOUR_SERVER_HOSTNAME/${hostname}/g" \
    -e "s/YOUR_SERVER_IP/${ip_address}/g" \
    "${workdir}/selfsigned.cnf" > "${workdir}/selfsigned.local.cnf"

openssl req -x509 -nodes -days 398 -newkey rsa:2048 \
    -keyout "${workdir}/../harnessd.key" \
    -out "${workdir}/../harnessd.crt" \
    -config "${workdir}/selfsigned.local.cnf"

chmod 600 "${workdir}/../harnessd.key"
