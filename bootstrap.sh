#!/usr/bin/env bash
# bootstrap.sh - Install Python dependencies for brain.py
# Run this at the start of each Cowork session (VM resets wipe packages).
#
# Usage:
#   bash /path/to/your-brain-folder/bootstrap.sh
#
# What it installs:
#   - numpy          (vector math)
#   - scikit-learn   (TF-IDF fallback embeddings)
#   - sentence-transformers (semantic embeddings, uses bundled model from _models/)
#
# After running, brain.py is ready for: ingest, search, graph, stats

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${SCRIPT_DIR}/_models/all-MiniLM-L6-v2"

echo "=== Brain Bootstrap ==="
echo "Installing Python dependencies..."

# Core deps (these always work on the VM)
pip3 install --break-system-packages --quiet numpy scikit-learn 2>&1 | tail -1

# sentence-transformers (the library, not the model - model is bundled in _models/)
echo "Installing sentence-transformers..."
if pip3 install --break-system-packages --quiet sentence-transformers 2>&1 | tail -1; then
    ST_OK=true
else
    ST_OK=false
    echo "  sentence-transformers install failed (will use TF-IDF fallback)"
fi

# Verify imports
python3 -c "
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
import numpy as np
print('OK: scikit-learn + numpy ready')
"

if [ "$ST_OK" = true ]; then
    python3 -c "
from sentence_transformers import SentenceTransformer
print('OK: sentence-transformers ready')
" 2>/dev/null || echo "  sentence-transformers import failed (will use TF-IDF fallback)"
fi

# Check for bundled model
if [ -f "${MODEL_DIR}/config.json" ] && [ -f "${MODEL_DIR}/model.safetensors" ]; then
    echo "OK: Embedding model bundled (all-MiniLM-L6-v2)"
else
    echo "WARNING: Embedding model not found in _models/all-MiniLM-L6-v2/."
    echo "         Search will fall back to TF-IDF (keyword-based, still functional)."
fi

# Quick sanity: can brain.py parse?
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('brain', '${SCRIPT_DIR}/brain.py'); print('OK: brain.py loadable')"

echo "=== Bootstrap complete ==="
echo "Ready: python3 ${SCRIPT_DIR}/brain.py [ingest|search|graph|stats]"
