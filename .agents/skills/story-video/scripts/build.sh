#!/usr/bin/env bash
#   build.sh draft PROJECT            voice it, render a 540p draft + contact sheets
#   build.sh final PROJECT [OUT.mp4]  1080p, 30 fps, with subtitles, description and thumbnail
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mode="${1:-}"; project="${2:-}"
[ -n "$mode" ] && [ -n "$project" ] || { echo "usage: build.sh draft|final PROJECT [OUT.mp4]"; exit 1; }
project="$(cd "$project" && pwd)"
node "$here/narrate.mjs" "$project"
case "$mode" in
  draft) node "$here/render.mjs" "$project" --draft ;;
  final) node "$here/render.mjs" "$project" --final ${3:+--out "$3"} ;;
  *) echo "mode must be draft or final"; exit 1 ;;
esac
