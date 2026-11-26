#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$native"; mkdir -p sbt-warm/project; cd sbt-warm; cp "$cy/project/build.properties" project/; cp "$cy/project/plugins.sbt" project/; java $SBT_OPTS -jar "$cy/scripts/sbt-launch.jar" 'show sbtVersion'
