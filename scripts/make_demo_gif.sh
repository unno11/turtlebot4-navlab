#!/usr/bin/env bash
# Turn a screen recording of a navigation run into the demo GIF used in the README.
#
# Screen recordings are long (a real run takes minutes of wall clock) and start with
# the window title bar, so this trims the bar, speeds the clip up, scales it down and
# writes a palette-optimised GIF. Everything is parameterised so the clip can be
# retuned without touching the script.
#
# Usage:
#   ./scripts/make_demo_gif.sh recording.mp4
#   SPEED=16 WIDTH=800 ./scripts/make_demo_gif.sh recording.mp4 docs/media/navlab-demo.gif
#
# Environment:
#   SPEED    playback multiplier, 12 means 12x faster than real time   (default 12)
#   FPS      GIF frame rate                                            (default 12)
#   WIDTH    output width in pixels, height follows the aspect ratio   (default 960)
#   CROP_TOP pixels of window title bar to cut off the top              (default 32)
#   START    seconds to skip at the beginning                          (default 0)
#   DURATION seconds to keep, empty means whole clip                   (default empty)

set -euo pipefail

IN="${1:-}"
OUT="${2:-docs/media/navlab-demo.gif}"
SPEED="${SPEED:-12}"
FPS="${FPS:-12}"
WIDTH="${WIDTH:-960}"
CROP_TOP="${CROP_TOP:-32}"
START="${START:-0}"
DURATION="${DURATION:-}"

if [[ -z "$IN" || ! -f "$IN" ]]; then
  echo "用法：$0 <录屏文件> [输出 GIF]" >&2
  exit 1
fi

command -v ffmpeg >/dev/null || { echo "错误：找不到 ffmpeg" >&2; exit 1; }

mkdir -p "$(dirname -- "$OUT")"

trim=()
[[ "$START" != "0" ]] && trim+=(-ss "$START")
[[ -n "$DURATION" ]] && trim+=(-t "$DURATION")

filters="crop=iw:ih-${CROP_TOP}:0:${CROP_TOP}"
filters+=",setpts=PTS/${SPEED}"
filters+=",fps=${FPS}"
filters+=",scale=${WIDTH}:-1:flags=lanczos"
filters+=",split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"

echo "输入 : $IN"
echo "输出 : $OUT"
echo "参数 : ${SPEED}x 速度, ${FPS} fps, ${WIDTH} px 宽"

ffmpeg -hide_banner -loglevel warning "${trim[@]}" -i "$IN" -vf "$filters" -loop 0 -y "$OUT"

size=$(stat -c '%s' "$OUT")
echo "完成：$OUT（$((size / 1024)) KB）"
if (( size > 9 * 1024 * 1024 )); then
  echo "提示：超过 9 MB，可调小 WIDTH 或调大 SPEED 再转一次。" >&2
fi
