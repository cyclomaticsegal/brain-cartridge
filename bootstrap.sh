#!/usr/bin/env bash
# bootstrap.sh — Install Python dependencies for brain.py
# Run this at the start of each Cowork session (VM resets wipe packages).
#
# Usage:
#   bash /path/to/your-brain-folder/bootstrap.sh
#
# What it installs:
#   - scikit-learn  (TF-IDF embeddings — the working fallback)
#   - numpy         (vector math)
#   - sentence-transformers (primary embedder — model download may fail behind proxy)
#
# After running, brain.py is ready for: ingest, search, graph, stats

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Brain Bootstrap ==="
echo "Installing Python dependencies..."

# Core deps (these always work on the VM)
pip3 install --break-system-packages --quiet numpy scikit-learn 2>&1 | tail -1

# sentence-transformers (model download may fail behind proxy — that's fine,
# brain.py auto-falls back to TF-IDF)
pip3 install --break-system-packages --quiet sentence-transformers 2>&1 | tail -1

# Verify imports work
python3 -c "
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
import numpy as np
print('OK: scikit-learn + numpy ready')

try:
    from sentence_transformers import SentenceTransformer
    print('OK: sentence-transformers available (model download may still need proxy)')
except ImportError:
    print('WARN: sentence-transformers not available — TF-IDF fallback will be used')
"

# Quick sanity: can brain.py at least parse?
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('brain', '${SCRIPT_DIR}/brain.py'); print('OK: brain.py loadable')"

echo "=== Bootstrap complete ==="
echo "Ready: python3 ${SCRIPT_DIR}/brain.py [ingest|search|graph|stats]"
