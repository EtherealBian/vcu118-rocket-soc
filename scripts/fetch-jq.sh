#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cache=$root/cache
cd "$cache"; u=https://github.com/jqlang/jq/releases/download/jq-1.7.1
curl -fLsS --retry 2 "$u/sha256sum.txt" -o jq-1.7.1.sha256
if ! test -s jq-linux-amd64; then curl -fLsS --retry 2 "$u/jq-linux-amd64" -o jq-linux-amd64.part; mv jq-linux-amd64.part jq-linux-amd64; fi
grep -E '  jq-linux-amd64$' jq-1.7.1.sha256 | sha256sum -c -; install -Dm755 jq-linux-amd64 "$tools/bin/jq"; "$tools/bin/jq" --version
