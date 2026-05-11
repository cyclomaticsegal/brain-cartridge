#!/usr/bin/env bash
# download-model.sh
#
# Downloads the all-MiniLM-L6-v2 embedding model into _models/.
# Run this ONCE from your real terminal (not inside Cowork).
# The Cowork VM proxy blocks HuggingFace, so this must run outside it.
#
# After running, the model files are committed to the repo and available
# to every user who clones it. No runtime download needed.
#
# Usage:
#   cd brain-cartridge
#   bash download-model.sh

set -e

MODEL_DIR="_models/all-MiniLM-L6-v2"
POOLING_DIR="${MODEL_DIR}/1_Pooling"
BASE_URL="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"

echo "=== Downloading all-MiniLM-L6-v2 embedding model ==="
echo "Target: ${MODEL_DIR}/"

mkdir -p "${MODEL_DIR}" "${POOLING_DIR}"

# Core config files (small, <1MB total)
for f in config.json config_sentence_transformers.json modules.json \
         sentence_bert_config.json special_tokens_map.json \
         tokenizer.json tokenizer_config.json vocab.txt; do
    echo "  Downloading ${f}..."
    curl -sL "${BASE_URL}/${f}" -o "${MODEL_DIR}/${f}"
done

# Pooling config
echo "  Downloading 1_Pooling/config.json..."
curl -sL "${BASE_URL}/1_Pooling/config.json" -o "${POOLING_DIR}/config.json"

# Model weights (90.9 MB)
echo "  Downloading model.safetensors (90.9 MB)..."
curl -L --progress-bar "${BASE_URL}/model.safetensors" -o "${MODEL_DIR}/model.safetensors"

# Verify
if [ -f "${MODEL_DIR}/model.safetensors" ] && [ -f "${MODEL_DIR}/config.json" ]; then
    SIZE=$(du -sh "${MODEL_DIR}" | cut -f1)
    echo ""
    echo "=== Download complete ==="
    echo "Model directory: ${MODEL_DIR}/ (${SIZE})"
    echo ""
    echo "Next steps:"
    echo "  git add _models/"
    echo "  git commit -m 'Add bundled all-MiniLM-L6-v2 embedding model'"
    echo "  git push"
else
    echo ""
    echo "ERROR: Download failed. Check your internet connection and try again."
    exit 1
fi
