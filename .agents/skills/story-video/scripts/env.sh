#!/usr/bin/env bash
# Source this, then call story_env_check. The tool cache is shared with the
# product-demo-video skill, so installing either one serves both.
export VIDEO_TOOLS_HOME="${VIDEO_TOOLS_HOME:-${DEMO_VIDEO_HOME:-$HOME/.cache/product-demo-video}}"
export STORY_VIDEO_SKILL="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

story_env_check() {
  local ok=0
  say_ok()  { printf '  ok       %s\n' "$1"; }
  say_bad() { printf '  MISSING  %s\n' "$1"; ok=1; }
  if command -v node >/dev/null 2>&1 && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ]; then say_ok "node $(node -v)"; else say_bad "node >= 20"; fi
  for dep in playwright kokoro-js; do
    if [ -d "$VIDEO_TOOLS_HOME/node_modules/$dep" ]; then say_ok "$dep"; else say_bad "$dep (run scripts/setup.sh)"; fi
  done
  if command -v ffmpeg >/dev/null 2>&1; then say_ok "ffmpeg (system)"
  elif [ -d "$VIDEO_TOOLS_HOME/node_modules/ffmpeg-static" ]; then say_ok "ffmpeg (bundled ffmpeg-static)"
  else say_bad "ffmpeg (run scripts/setup.sh)"; fi
  if [ -f "$VIDEO_TOOLS_HOME/.chromium-ok" ]; then say_ok "chromium for playwright"; else say_bad "chromium (run scripts/setup.sh)"; fi
  return $ok
}
