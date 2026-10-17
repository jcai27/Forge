#!/usr/bin/env bash
# One-time install: Playwright + Chromium (the renderer), a full ffmpeg, the Kokoro voice.
set -euo pipefail
. "$(dirname "$0")/env.sh"
mkdir -p "$VIDEO_TOOLS_HOME"
cd "$VIDEO_TOOLS_HOME"
[ -f package.json ] || printf '{"name":"video-tools-cache","private":true}\n' > package.json
npm install --no-audit --no-fund --loglevel=error playwright ffmpeg-static kokoro-js
npx playwright install chromium
touch .chromium-ok
story_env_check
