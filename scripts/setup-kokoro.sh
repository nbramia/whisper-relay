#!/usr/bin/env bash
set -euo pipefail
DIR="${HOME}/.local/share/whisper-relay/tts/kokoro"
mkdir -p "$DIR"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [[ ! -f "$DIR/$f" ]]; then
    echo "Downloading $f..."
    wget -q -O "$DIR/$f" "$BASE/$f"
  else
    echo "Already have $f"
  fi
done
echo "Kokoro models ready in $DIR"
