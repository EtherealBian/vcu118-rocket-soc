#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
bash scripts/fetch-image-sources.sh linux > logs/source-linux.txt 2>&1 & a=$!
bash scripts/fetch-image-sources.sh busybox > logs/source-busybox.txt 2>&1 & b=$!
bash scripts/fetch-image-sources.sh opensbi > logs/source-opensbi.txt 2>&1 & c=$!
ok=0; for job in "$a" "$b" "$c"; do wait "$job" || ok=1; done; exit "$ok"
