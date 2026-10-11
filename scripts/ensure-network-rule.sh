#!/usr/bin/env bash
set -euo pipefail
subnet=$(docker network inspect kinosfera_default --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
[[ -n "$subnet" ]] || { echo 'Project network does not exist.' >&2; exit 1; }
# The binary initializes with an HTTP request to a DNS-only IP address.
# Reject that unreachable TCP service promptly; do not replace its response.
rule=(-s "$subnet" -d 8.8.8.8/32 -p tcp --dport 80
      -m comment --comment kinosfera-init-timeout -j REJECT --reject-with tcp-reset)
iptables -C DOCKER-USER "${rule[@]}" 2>/dev/null || iptables -I DOCKER-USER 1 "${rule[@]}"
