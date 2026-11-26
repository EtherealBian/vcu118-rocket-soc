#!/usr/bin/env bash
set -u
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
bash scripts/generator-tools.sh java > logs/jdk.txt 2>&1 & a=$!
bash scripts/generator-tools.sh firtool > logs/firtool.txt 2>&1 & b=$!
wait "$a"; x=$?; wait "$b" && exit "$x"; exit 1
