#!/usr/bin/env python3
"""
brain.py: Personal knowledge base engine.

Unified SQLite storage with hybrid search (BM25 keyword + semantic vector).
See ADR-001 for architectural rationale.

Usage:
    # Ingest all source files and rebuild the database
    python3 brain.py ingest

    # Hybrid search (keyword + semantic, fused via RRF)
    python3 brain.py search "energy constraints on AI scaling"

    # Keyword-only search (BM25 via FTS5)
    python3 brain.py search --mode keyword "tokenization"

    # Semantic-only search (vector cosine similarity)
    python3 brain.py search --mode semantic "what happens to human purpose"

    # Graph query: show all concepts connected to a node
    python3 brain.py graph C11

    # Graph query: show all concepts within N hops
    python3 brain.py graph C11 --hops 2

    # Export graph from DB to GRAPH.json + update graph-explorer.html
    python3 brain.py export-graph

    # Update graph-explorer.html from DB (without writing GRAPH.json)
    python3 brain.py update-html

    # Tag a source with domains (manual override / correction)
    python3 brain.py tag S41 10,12 "knowledge entrepreneurship, generalist thesis"

    # Stats
    python3 brain.py stats
"""

import sqlite3
import json
import struct
import sys
import os
import re
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
# SQLite needs a real filesystem (not FUSE mounts). The VM session dir provides
# this. On startup, we restore from the persistent workspace copy. On every
# write, we export back to the workspace. This gives us both:
#   - Fast, reliable SQLite operations (session dir)
#   - Persistence across VM resets (workspace mount)


def _detect_session_dir() -> Optional[Path]:
    """Auto-detect the Cowork VM session directory.

    Each Cowork task gets a unique session name (e.g. /sessions/charming-purple-fox/).
    Rather than hardcoding, we scan /sessions/ for the actual directory.
    Falls back gracefully: if not running in a Cowork VM, returns None and
    brain.db operates directly from the workspace folder.
    """
    sessions_root = Path("/sessions")
    if not sessions_root.exists():
        return None  # Not running in a Cowork VM
    candidates = [d for d in sessions_root.iterdir()
                  if d.is_dir() and not d.name.startswith(".")]
    if len(candidates) == 1:
        return candidates[0]
    # Multiple or zero, can't determine, fall back to workspace
    return None


_SESSION_DIR = _detect_session_dir()
DB_PATH = (_SESSION_DIR / "brain.db") if _SESSION_DIR else (BASE_DIR / "brain.db")
GRAPH_JSON = BASE_DIR / "GRAPH.json"
GRAPH_HTML = BASE_DIR / "graph-explorer.html"
# Persistent copy in workspace (survives VM resets)
DB_EXPORT_PATH = BASE_DIR / "brain.db"


def _restore_db_from_workspace():
    """Restore brain.db from workspace if the session copy is missing/empty.

    This runs once at module import time. The workspace copy persists on the
    user's actual filesystem across VM resets. Without this, every new session
    would start with an empty database requiring a full re-ingest.
    """
    if DB_PATH == DB_EXPORT_PATH:
        return  # Same file, no restore needed

    session_exists = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    workspace_exists = DB_EXPORT_PATH.exists() and DB_EXPORT_PATH.stat().st_size > 0

    if not session_exists and workspace_exists:
        import shutil
        shutil.copy2(str(DB_EXPORT_PATH), str(DB_PATH))
        print(f"  Restored brain.db from workspace ({DB_EXPORT_PATH.stat().st_size / 1024:.0f} KB)")


# Restore on import: ensures the DB is available before any operations
_restore_db_from_workspace()

# Chunking parameters
CHUNK_SIZE = 512        # target tokens per chunk (approx chars / 4)
CHUNK_OVERLAP = 64      # token overlap between chunks
CHUNK_CHARS = CHUNK_SIZE * 4
OVERLAP_CHARS = CHUNK_OVERLAP * 4

# Embedding model
# Primary: sentence-transformers with bundled model weights (no download needed)
# Fallback: TF-IDF from scikit-learn (if sentence-transformers package unavailable)
MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_LOCAL_DIR = BASE_DIR / "_models" / MODEL_NAME  # bundled in repo
EMBEDDING_DIM = 384  # overridden at runtime if using TF-IDF
EMBEDDING_BACKEND = "auto"  # "auto", "sentence-transformers", or "tfidf"

# Search defaults
DEFAULT_TOP_K = 10
RRF_K = 60  # reciprocal rank fusion constant

# Source file extensions to ingest
INGEST_EXTENSIONS = {".md", ".txt", ".pdf"}

# Note: ingestion scans sources/ only (see find_source_files).
# No skip-list needed. Files enter sources/ via process_inbox().


# ---------------------------------------------------------------------------
# Embedding engine (pluggable: sentence-transformers or TF-IDF fallback)
# ---------------------------------------------------------------------------

_embedder = None


class TFIDFEmbedder:
    """TF-IDF based embeddings using scikit-learn. Always available, no downloads.
    Not true semantic search, but captures term importance and distributional
    similarity. Combined with BM25 keyword search, provides solid hybrid retrieval.
    Swap to SentenceTransformerEmbedder when running on a machine that can
    download from HuggingFace."""

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vectorizer = TfidfVectorizer(
            max_features=2048,
            sublinear_tf=True,
            strip_accents="unicode",
            ngram_range=(1, 2),  # unigrams + bigrams for better phrase matching
            min_df=1,
            max_df=0.95,
        )
        self._fitted = False
        self._corpus_vectors = None

    def fit(self, texts: list[str]):
        """Fit TF-IDF on the full corpus."""
        self.vectorizer.fit(texts)
        self._fitted = True

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate TF-IDF vectors. Must call fit() first for corpus."""
        if not self._fitted:
            self.fit(texts)
        matrix = self.vectorizer.transform(texts)
        # Normalize rows to unit vectors for cosine similarity via dot product
        from sklearn.preprocessing import normalize
        matrix = normalize(matrix, norm="l2")
        return matrix.toarray().tolist()

    def embed_single(self, text: str) -> list[float]:
        """Embed a single query text."""
        if not self._fitted:
            raise RuntimeError("TF-IDF model not fitted. Run ingest first.")
        matrix = self.vectorizer.transform([text])
        from sklearn.preprocessing import normalize
        matrix = normalize(matrix, norm="l2")
        return matrix.toarray()[0].tolist()

    @property
    def dim(self):
        return self.vectorizer.max_features if self._fitted else 2048


class SentenceTransformerEmbedder:
    """Sentence-transformers embeddings using bundled model weights.

    The model (all-MiniLM-L6-v2) is bundled in _models/ within the repo.
    No HuggingFace download needed at runtime. If the bundled model is
    missing, falls back to attempting a HuggingFace download (which will
    fail behind the Cowork proxy, triggering TF-IDF fallback).
    """

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        # Suppress HuggingFace download attempts when using local model
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        if MODEL_LOCAL_DIR.exists() and (MODEL_LOCAL_DIR / "config.json").exists():
            # Load from bundled model directory
            self.model = SentenceTransformer(str(MODEL_LOCAL_DIR))
        else:
            # Bundled model not found, try HuggingFace download (unlikely to work in Cowork)
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            cache_dir = BASE_DIR / ".cache" / "models"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.model = SentenceTransformer(MODEL_NAME, cache_folder=str(cache_dir))

    def fit(self, texts: list[str]):
        pass  # Pre-trained, no fitting needed

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts, show_progress_bar=len(texts) > 50,
                                       normalize_embeddings=True)
        return embeddings.tolist()

    def embed_single(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    @property
    def dim(self):
        return EMBEDDING_DIM


def get_embedder():
    """Get or initialize the embedding engine."""
    global _embedder
    if _embedder is not None:
        return _embedder

    backend = EMBEDDING_BACKEND

    if backend == "auto":
        # Try sentence-transformers first, fall back to TF-IDF
        try:
            _embedder = SentenceTransformerEmbedder()
            print("  Embedding backend: sentence-transformers")
        except Exception as e:
            print(f"  sentence-transformers unavailable ({type(e).__name__}), using TF-IDF")
            _embedder = TFIDFEmbedder()
            print("  Embedding backend: TF-IDF (scikit-learn)")
    elif backend == "sentence-transformers":
        _embedder = SentenceTransformerEmbedder()
    else:
        _embedder = TFIDFEmbedder()
        print("  Embedding backend: TF-IDF (scikit-learn)")

    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts."""
    return get_embedder().embed_texts(texts)


def embed_single(text: str) -> list[float]:
    """Generate embedding for a single text."""
    return get_embedder().embed_single(text)


# ---------------------------------------------------------------------------
# Vector serialization (float32 → bytes)
# ---------------------------------------------------------------------------

def vec_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def bytes_to_vec(b: bytes) -> list[float]:
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    import numpy as np
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

SCHEMA = """
-- Graph structure
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('domain', 'concept', 'source', 'prediction')),
    group_id INTEGER,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    type TEXT NOT NULL,
    label TEXT,
    UNIQUE(source_id, target_id, type)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);

-- Document chunks for RAG
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    char_start INTEGER,
    char_end INTEGER,
    metadata TEXT DEFAULT '{}',
    UNIQUE(source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

-- FTS5 for keyword search (BM25)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

-- Vector embeddings (stored as float32 BLOBs)
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id),
    embedding BLOB NOT NULL
);

-- Metadata
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Predictions (model tracking: single source of truth for pipeline state)
CREATE TABLE IF NOT EXISTS predictions (
    model_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    model_type TEXT DEFAULT 'Advanced',
    status TEXT NOT NULL DEFAULT 'queued',
    quality TEXT DEFAULT NULL,
    quality_reason TEXT DEFAULT NULL,
    progress INTEGER DEFAULT 0,
    status_label TEXT DEFAULT '',
    short_summary TEXT DEFAULT '',
    outcomes TEXT DEFAULT '[]',
    outcome_probs TEXT DEFAULT NULL,
    edge_stats TEXT DEFAULT NULL,
    driver_count INTEGER DEFAULT 0,
    source_thesis TEXT DEFAULT NULL,
    report_fetched INTEGER DEFAULT 0,
    narrative_generated INTEGER DEFAULT 0,
    ingested_to_brain INTEGER DEFAULT 0,
    added_to_graph INTEGER DEFAULT 0,
    graph_node_id TEXT DEFAULT NULL,
    platform_model_id TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT DEFAULT NULL,
    updated_at TEXT NOT NULL,
    artifacts_path TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status);
CREATE INDEX IF NOT EXISTS idx_predictions_quality ON predictions(quality);
"""


def init_db() -> sqlite3.Connection:
    """Initialize database with schema."""
    conn = sqlite3.connect(str(DB_PATH))
    # WAL mode for better write perf (only works on real filesystems)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass  # Fall back to default journal mode on FUSE mounts
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def export_db_to_workspace():
    """Copy brain.db to workspace folder for persistence between sessions."""
    import shutil
    if DB_PATH != DB_EXPORT_PATH and DB_PATH.exists():
        shutil.copy2(str(DB_PATH), str(DB_EXPORT_PATH))
        print(f"  Exported DB to {DB_EXPORT_PATH} ({DB_EXPORT_PATH.stat().st_size / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# Predictions table CRUD
# ---------------------------------------------------------------------------

def save_prediction(model_id: str, question: str, **kwargs) -> dict:
    """
    Insert or update a prediction record in brain.db.
    All pipeline state lives here, not in JSON files.

    Required: model_id, question
    Optional kwargs: model_type, status, quality, quality_reason, progress,
        status_label, short_summary, outcomes (list), outcome_probs (dict),
        edge_stats (dict), driver_count, source_thesis, report_fetched (bool),
        narrative_generated (bool), ingested_to_brain (bool), added_to_graph (bool),
        graph_node_id, platform_model_id, created_at, completed_at, artifacts_path
    """
    conn = init_db()
    now = datetime.now().isoformat()

    # Serialize list/dict fields to JSON strings
    outcomes = kwargs.get("outcomes", [])
    if isinstance(outcomes, list):
        outcomes = json.dumps(outcomes)
    outcome_probs = kwargs.get("outcome_probs")
    if isinstance(outcome_probs, dict):
        outcome_probs = json.dumps(outcome_probs)
    edge_stats = kwargs.get("edge_stats")
    if isinstance(edge_stats, dict):
        edge_stats = json.dumps(edge_stats)

    conn.execute("""
        INSERT INTO predictions (
            model_id, question, model_type, status, quality, quality_reason,
            progress, status_label, short_summary, outcomes, outcome_probs,
            edge_stats, driver_count, source_thesis, report_fetched,
            narrative_generated, ingested_to_brain, added_to_graph,
            graph_node_id, platform_model_id, created_at, completed_at,
            updated_at, artifacts_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(model_id) DO UPDATE SET
            question=excluded.question,
            model_type=excluded.model_type,
            status=excluded.status,
            quality=excluded.quality,
            quality_reason=excluded.quality_reason,
            progress=excluded.progress,
            status_label=excluded.status_label,
            short_summary=excluded.short_summary,
            outcomes=excluded.outcomes,
            outcome_probs=excluded.outcome_probs,
            edge_stats=excluded.edge_stats,
            driver_count=excluded.driver_count,
            source_thesis=excluded.source_thesis,
            report_fetched=excluded.report_fetched,
            narrative_generated=excluded.narrative_generated,
            ingested_to_brain=excluded.ingested_to_brain,
            added_to_graph=excluded.added_to_graph,
            graph_node_id=excluded.graph_node_id,
            platform_model_id=excluded.platform_model_id,
            completed_at=excluded.completed_at,
            updated_at=excluded.updated_at,
            artifacts_path=excluded.artifacts_path
    """, (
        model_id,
        question,
        kwargs.get("model_type", "Advanced"),
        kwargs.get("status", "queued"),
        kwargs.get("quality"),
        kwargs.get("quality_reason"),
        kwargs.get("progress", 0),
        kwargs.get("status_label", ""),
        kwargs.get("short_summary", ""),
        outcomes,
        outcome_probs,
        edge_stats,
        kwargs.get("driver_count", 0),
        kwargs.get("source_thesis"),
        int(kwargs.get("report_fetched", False)),
        int(kwargs.get("narrative_generated", False)),
        int(kwargs.get("ingested_to_brain", False)),
        int(kwargs.get("added_to_graph", False)),
        kwargs.get("graph_node_id"),
        kwargs.get("platform_model_id"),
        kwargs.get("created_at", now),
        kwargs.get("completed_at"),
        now,
        kwargs.get("artifacts_path"),
    ))
    conn.commit()
    conn.close()
    export_db_to_workspace()
    return get_prediction(model_id)


def update_prediction(model_id: str, **kwargs) -> dict:
    """
    Update specific fields on an existing prediction.
    Only provided kwargs are updated; others left unchanged.
    """
    conn = init_db()
    now = datetime.now().isoformat()

    # Build SET clause dynamically from provided kwargs
    allowed = {
        "question", "model_type", "status", "quality", "quality_reason",
        "progress", "status_label", "short_summary", "outcomes", "outcome_probs",
        "edge_stats", "driver_count", "source_thesis", "report_fetched",
        "narrative_generated", "ingested_to_brain", "added_to_graph",
        "graph_node_id", "platform_model_id", "completed_at", "artifacts_path"
    }

    sets = ["updated_at = ?"]
    values = [now]

    for key, val in kwargs.items():
        if key not in allowed:
            continue
        # Serialize list/dict fields
        if key in ("outcomes", "outcome_probs", "edge_stats") and isinstance(val, (dict, list)):
            val = json.dumps(val)
        # Bool fields stored as int
        if key in ("report_fetched", "narrative_generated", "ingested_to_brain", "added_to_graph"):
            val = int(val)
        sets.append(f"{key} = ?")
        values.append(val)

    values.append(model_id)
    sql = f"UPDATE predictions SET {', '.join(sets)} WHERE model_id = ?"
    conn.execute(sql, values)
    conn.commit()
    conn.close()
    export_db_to_workspace()
    return get_prediction(model_id)


def get_prediction(model_id: str) -> Optional[dict]:
    """Fetch a single prediction by model_id. Returns dict or None."""
    conn = init_db()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM predictions WHERE model_id = ?", (model_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    # Deserialize JSON fields
    for key in ("outcomes", "outcome_probs", "edge_stats"):
        if d.get(key) and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    # Bool fields
    for key in ("report_fetched", "narrative_generated", "ingested_to_brain", "added_to_graph"):
        d[key] = bool(d.get(key, 0))
    return d


def list_predictions(status: str = None, quality: str = None) -> list[dict]:
    """
    List all predictions, optionally filtered by status and/or quality.
    Returns list of dicts sorted by created_at desc.
    """
    conn = init_db()
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM predictions WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if quality:
        sql += " AND quality = ?"
        params.append(quality)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        for key in ("outcomes", "outcome_probs", "edge_stats"):
            if d.get(key) and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        for key in ("report_fetched", "narrative_generated", "ingested_to_brain", "added_to_graph"):
            d[key] = bool(d.get(key, 0))
        results.append(d)
    return results


# ---------------------------------------------------------------------------
# Document chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_chars: int = CHUNK_CHARS,
               overlap_chars: int = OVERLAP_CHARS) -> list[dict]:
    """Split text into overlapping chunks.

    Strategy: split on section dividers (---) first, then on double newlines,
    then on single newlines, then on sentence boundaries. Ensures no chunk
    exceeds chunk_chars.
    """
    # First split on horizontal rules (common in these docs)
    sections = re.split(r'\n-{3,}\n', text.strip())
    if len(sections) == 1:
        # No section dividers; split on double newlines
        sections = re.split(r'\n{2,}', text.strip())

    # Further split any section that's still too large
    fine_sections = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= chunk_chars:
            fine_sections.append(section)
        else:
            # Split large sections on single newlines
            lines = section.split('\n')
            sub = ""
            for line in lines:
                if len(sub) + len(line) + 1 > chunk_chars and sub:
                    fine_sections.append(sub.strip())
                    sub = line
                else:
                    sub = (sub + "\n" + line) if sub else line
            if sub.strip():
                fine_sections.append(sub.strip())

    # Now accumulate into chunks with overlap
    chunks = []
    current = ""
    char_pos = 0

    for section in fine_sections:
        if len(current) + len(section) + 2 > chunk_chars and current:
            chunks.append({
                "content": current.strip(),
                "char_start": char_pos - len(current),
                "char_end": char_pos
            })
            if overlap_chars > 0 and len(current) > overlap_chars:
                overlap_text = current[-overlap_chars:]
                current = overlap_text + "\n\n" + section
            else:
                current = section
        else:
            current = (current + "\n\n" + section) if current else section

        char_pos += len(section) + 2

    if current.strip():
        chunks.append({
            "content": current.strip(),
            "char_start": char_pos - len(current),
            "char_end": char_pos
        })

    return chunks


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF using pdftotext (poppler-utils)."""
    import subprocess
    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError:
        pass
    print(f"  WARNING: Could not extract text from PDF: {path}")
    return ""


def find_source_files() -> list[Path]:
    """Find all ingestible source files in sources/ only.

    Ingestion scans ONLY the sources/ directory. Files get into sources/
    via process_inbox(), which moves them from inbox/ to sources/ with
    clean naming and source IDs. This prevents accidental ingestion of
    README.md, CLAUDE.md, SKILL.md, AXIOMS.md, demo files, and other
    repo files that are not user content.
    """
    sources_dir = BASE_DIR / "sources"
    if not sources_dir.exists():
        return []
    files = []
    for path in sources_dir.rglob("*"):
        if path.is_dir():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in INGEST_EXTENSIONS:
            files.append(path)
    return sorted(files)


def file_to_source_id(path: Path) -> str:
    """Generate a stable source ID from file path.

    If the filename starts with an SXX- prefix (e.g. S01-the-great-inversion.md),
    use that as the source ID directly. Otherwise fall back to hash-based ID.
    """
    stem = path.stem
    # Check for SXX- prefix pattern
    m = re.match(r'^(S\d{2})-', stem)
    if m:
        return m.group(1)
    # Fallback: hash-based ID
    rel = path.relative_to(BASE_DIR)
    h = hashlib.md5(str(rel).encode()).hexdigest()[:6]
    clean = re.sub(r'[^a-zA-Z0-9]', '-', stem)[:20]
    return f"S_{clean}_{h}"


def ingest_graph_json(conn: sqlite3.Connection):
    """Import nodes and edges from GRAPH.json into SQLite (one-time migration).

    Only imports if the nodes table is empty. After the first import, brain.db
    is the sole authority for graph data. GRAPH.json becomes a derived export.
    """
    n_existing = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    if n_existing > 0:
        print(f"  Graph already in DB ({n_existing} nodes), skipping GRAPH.json import")
        return

    if not GRAPH_JSON.exists():
        print("  GRAPH.json not found and DB is empty, no graph data available")
        return

    data = json.loads(GRAPH_JSON.read_text())

    for node in data["nodes"]:
        conn.execute(
            "INSERT OR REPLACE INTO nodes (id, label, type, group_id, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (node["id"], node["label"], node["type"], node.get("group"),
             json.dumps({k: v for k, v in node.items()
                        if k not in ("id", "label", "type", "group")}))
        )

    for edge in data["edges"]:
        conn.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, type, label) "
            "VALUES (?, ?, ?, ?)",
            (edge["source"], edge["target"], edge["type"], edge.get("label"))
        )

    conn.commit()
    print(f"  Migrated from GRAPH.json: {len(data['nodes'])} nodes, {len(data['edges'])} edges")


# ---------------------------------------------------------------------------
# Graph mutation API (database is the source of truth)
# ---------------------------------------------------------------------------

def add_node(node_id: str, label: str, node_type: str, group_id: int = None,
             metadata: dict = None, conn: sqlite3.Connection = None) -> bool:
    """Add or update a node in the graph. Returns True if inserted, False if updated."""
    close = False
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH))
        close = True

    existing = conn.execute("SELECT id FROM nodes WHERE id=?", (node_id,)).fetchone()
    meta_json = json.dumps(metadata or {})

    conn.execute(
        "INSERT OR REPLACE INTO nodes (id, label, type, group_id, metadata) "
        "VALUES (?, ?, ?, ?, ?)",
        (node_id, label, node_type, group_id, meta_json)
    )
    conn.commit()

    if close:
        conn.close()
    return existing is None


def add_edge(source_id: str, target_id: str, edge_type: str,
             label: str = None, conn: sqlite3.Connection = None) -> bool:
    """Add an edge to the graph. Returns True if inserted, False if already existed."""
    close = False
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH))
        close = True

    try:
        conn.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, type, label) "
            "VALUES (?, ?, ?, ?)",
            (source_id, target_id, edge_type, label)
        )
        inserted = conn.total_changes > 0
        conn.commit()
    except sqlite3.IntegrityError:
        inserted = False

    if close:
        conn.close()
    return inserted


def get_graph_data() -> dict:
    """Read the full graph from the database. Returns JSON-serialisable dict."""
    conn = sqlite3.connect(str(DB_PATH))

    nodes = conn.execute("SELECT id, label, type, group_id, metadata FROM nodes").fetchall()
    edges = conn.execute("SELECT source_id, target_id, type, label FROM edges").fetchall()

    last_ingest = conn.execute(
        "SELECT value FROM meta WHERE key='last_ingest'").fetchone()

    data = {
        "meta": {
            "title": "Knowledge Graph",
            "updated": last_ingest[0] if last_ingest else datetime.now().isoformat(),
            "version": "2.0",
            "nodeCount": len(nodes),
            "edgeCount": len(edges)
        },
        "nodes": [],
        "edges": []
    }

    for n in nodes:
        node = {"id": n[0], "label": n[1], "type": n[2], "group": n[3]}
        meta = json.loads(n[4]) if n[4] else {}
        for k, v in meta.items():
            node[k] = v
        data["nodes"].append(node)

    for e in edges:
        edge = {"source": e[0], "target": e[1], "type": e[2]}
        if e[3]:
            edge["label"] = e[3]
        data["edges"].append(edge)

    conn.close()
    return data


def next_prediction_node_id(conn: sqlite3.Connection = None) -> str:
    """Get the next available prediction node ID (P01, P02, ...)."""
    close = False
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH))
        close = True

    rows = conn.execute(
        "SELECT id FROM nodes WHERE id LIKE 'P%' AND type='prediction'"
    ).fetchall()

    existing_nums = []
    for r in rows:
        try:
            existing_nums.append(int(r[0][1:]))
        except ValueError:
            pass

    next_num = max(existing_nums, default=0) + 1
    node_id = f"P{next_num:02d}"

    if close:
        conn.close()
    return node_id


def next_source_id() -> str:
    """Get the next available source ID (S14, S15, ...) based on files in sources/."""
    sources_dir = BASE_DIR / "sources"
    existing_nums = []
    if sources_dir.exists():
        for f in sources_dir.iterdir():
            m = re.match(r'^S(\d{2})-', f.stem)
            if m:
                existing_nums.append(int(m.group(1)))
    next_num = max(existing_nums, default=0) + 1
    return f"S{next_num:02d}"


def classify_source_domains(source_id: str, conn: sqlite3.Connection,
                            top_n: int = 2, threshold: float = 0.05) -> list[int]:
    """Auto-classify a source into domains using TF-IDF cosine similarity.

    Compares the source's chunk text against domain keyword descriptions.
    Returns the top_n domain numbers whose similarity exceeds the threshold.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    # Domain keyword descriptions: used as classification targets
    DOMAIN_DESCRIPTIONS = {
        1: "macroeconomics monetary systems fiscal policy interest rates inflation deflation sovereign debt central banking currency liquidity GDP economic growth bonds treasury yields credit markets financial system banking",
        2: "artificial intelligence machine learning AI agents LLM large language models neural networks deep learning compute scaling AGI automation cognitive augmentation machine cognition transformer models",
        3: "blockchain tokenization cryptocurrency digital ownership decentralization smart contracts ethereum bitcoin DeFi NFT token protocol web3 consensus mechanism distributed ledger",
        4: "innovation disruption theory technology adoption network effects competitive advantage moats startups entrepreneurship venture capital product market fit platform economics flywheel effects creative destruction",
        5: "energy infrastructure power grid data centers nuclear solar renewable electricity generation capacity compute hardware physical constraints supply chain commodities natural resources",
        6: "political economy governance institutions democracy regulation policy geopolitics sovereignty state power inequality wealth distribution social contract legitimacy power structures",
        7: "human purpose meaning consciousness qualia experience education learning creativity art culture identity work fulfilment wellbeing philosophy existential psychology motivation values",
        8: "geopolitics international relations trade wars sanctions military alliances geopolitical risk global order multipolar hegemony diplomacy national security",
        9: "meta personal self-reflection psychometric profile cognitive style personality traits OCEAN conscientiousness openness extraversion agreeableness neuroticism self-evaluation introspection",
        10: "consulting practice strategy client advisory workshop executive coaching AI adoption digital transformation business model industry targeting engagement delivery methodology market positioning knowledge entrepreneurship generalist specialist personal brand creator economy niche content distribution audience monetization",
        11: "predictions forecasting hypothesis Bayesian calibration confidence probability outcome tracking models future scenarios",
        12: "methodology meta-cognition cognitive profiling distillation pipeline knowledge architecture belief tracking calibration stress testing judgment framework decision architecture second brain cross-domain synthesis",
    }

    # Get all chunk text for this source
    chunks = conn.execute(
        "SELECT content FROM chunks WHERE source_id=?", (source_id,)
    ).fetchall()
    if not chunks:
        return []

    source_text = " ".join(c[0] for c in chunks)

    # Build corpus: domain descriptions + source text
    domain_ids = sorted(DOMAIN_DESCRIPTIONS.keys())
    corpus = [DOMAIN_DESCRIPTIONS[d] for d in domain_ids] + [source_text]

    vectorizer = TfidfVectorizer(stop_words='english', max_features=5000)
    tfidf_matrix = vectorizer.fit_transform(corpus)

    # Similarity of source (last row) against each domain description
    source_vec = tfidf_matrix[-1]
    domain_vecs = tfidf_matrix[:-1]
    similarities = cosine_similarity(source_vec, domain_vecs).flatten()

    # Rank and filter
    scored = sorted(zip(domain_ids, similarities), key=lambda x: -x[1])
    result = [d for d, s in scored[:top_n] if s >= threshold]

    # Always return at least one domain if any score is positive
    if not result and scored and scored[0][1] > 0:
        result = [scored[0][0]]

    return result


def wire_source_to_domains(source_id: str, domain_nums: list[int],
                           conn: sqlite3.Connection) -> list[str]:
    """Wire a source node to domain nodes. Creates domain nodes if missing.

    Returns list of actions taken (for logging).
    """
    actions = []

    for d in domain_nums:
        domain_node_id = f"D{d}" if d != 11 else "D_PRED"

        # Ensure domain node exists
        existing = conn.execute(
            "SELECT id FROM nodes WHERE id=?", (domain_node_id,)
        ).fetchone()
        if not existing:
            # Create domain node with canonical label
            domain_labels = {
                1: "Macroeconomics & Monetary Systems",
                2: "AI & Machine Intelligence",
                3: "Blockchain, Tokenization & Ownership",
                4: "Innovation & Disruption Theory",
                5: "Energy & Physical Infrastructure",
                6: "Political Economy & Governance",
                7: "Human Purpose & Meaning",
                8: "Geopolitics",
                9: "Meta / Personal",
                10: "Applied: AI Adoption Consulting",
                11: "Predictions",
                12: "Consulting Methodology & Meta-Cognition",
            }
            label = domain_labels.get(d, f"Domain {d}")
            conn.execute(
                "INSERT INTO nodes (id, label, type, group_id, metadata) "
                "VALUES (?, ?, 'domain', ?, '{}')",
                (domain_node_id, label, d)
            )
            actions.append(f"Created domain node {domain_node_id} ({label})")

        # Wire edge (skip if exists)
        existing_edge = conn.execute(
            "SELECT 1 FROM edges WHERE source_id=? AND target_id=?",
            (domain_node_id, source_id)
        ).fetchone()
        if not existing_edge:
            conn.execute(
                "INSERT INTO edges (source_id, target_id, type, label) "
                "VALUES (?, ?, 'contains', NULL)",
                (domain_node_id, source_id)
            )
            actions.append(f"Wired {source_id} → Domain {d}")

    # Update the source node's group_id to the first (strongest) domain
    if domain_nums:
        conn.execute(
            "UPDATE nodes SET group_id=? WHERE id=?",
            (domain_nums[0], source_id)
        )

    conn.commit()
    return actions


def tag_source(source_id: str, domain_nums: list[int], themes: str = None):
    """Manual domain tagging command. Wires graph edges, updates INDEX.md, exports graph.

    Usage: python3 brain.py tag S41 10,12 "key themes here"
    """
    conn = sqlite3.connect(str(DB_PATH))

    # Verify source exists
    existing = conn.execute(
        "SELECT id, label FROM nodes WHERE id=?", (source_id,)
    ).fetchone()
    if not existing:
        print(f"Error: source {source_id} not found in graph")
        conn.close()
        return

    print(f"Tagging {source_id} ({existing[1]}) → domains {domain_nums}")

    # Wire edges
    actions = wire_source_to_domains(source_id, domain_nums, conn)
    for a in actions:
        print(f"  {a}")

    conn.close()

    # Update INDEX.md row if themes provided
    if themes:
        index_path = BASE_DIR / "INDEX.md"
        if index_path.exists():
            text = index_path.read_text()
            # Find the TBD row for this source
            domain_str = ", ".join(str(d) for d in domain_nums)
            # Match both TBD and existing domain entries for this source
            pattern = rf'(\| {source_id} \| `[^`]+` \|) [^|]+ \| [^|]+ \|'
            replacement = rf'\1 {domain_str} | {themes} |'
            new_text = re.sub(pattern, replacement, text)
            if new_text != text:
                index_path.write_text(new_text)
                print(f"  Updated INDEX.md: {source_id} → domains {domain_str}, themes: {themes[:60]}...")
            else:
                print(f"  Warning: Could not find {source_id} row in INDEX.md to update")

    # Export graph
    export_db_to_workspace()
    export_graph_json()
    print(f"Tag complete.")


def process_inbox(domains: Optional[dict[str, list[int]]] = None):
    """Process files in the inbox/ folder (including all subfolders).

    1. Recursively finds all ingestible files in inbox/ and its subdirectories
    2. Assigns each file the next available SXX ID
    3. Moves it to sources/ with clean naming
    4. Runs ingestion on the new files
    5. Auto-classifies domains using TF-IDF similarity
    6. Wires source nodes to domain nodes in the graph
    7. Exports graph (GRAPH.json + graph-explorer.html)
    8. Cleans up inbox/: removes all processed files and empty subdirectories

    Args:
        domains: Optional mapping of original filename -> list of domain numbers.
                 If provided, overrides auto-classification for those files.
                 Example: {"new-paper.md": [1, 2, 5]}
    """
    import shutil

    inbox_dir = BASE_DIR / "inbox"
    if not inbox_dir.exists():
        print("No inbox/ directory found.")
        return []

    # Recursively find all ingestible files in inbox and subfolders
    inbox_files = []
    for f in sorted(inbox_dir.rglob("*")):
        if f.is_dir():
            continue
        if f.name.startswith("."):
            continue
        if f.suffix.lower() in INGEST_EXTENSIONS:
            inbox_files.append(f)

    if not inbox_files:
        print("Inbox is empty, nothing to process.")
        return []

    print(f"Found {len(inbox_files)} file(s) in inbox/")

    sources_dir = BASE_DIR / "sources"
    sources_dir.mkdir(exist_ok=True)
    processed = []

    for f in inbox_files:
        sid = next_source_id()
        # Clean the filename for the target
        clean_name = re.sub(r'[^a-zA-Z0-9._-]', '-', f.stem).strip('-').lower()
        # Collapse multiple dashes
        clean_name = re.sub(r'-+', '-', clean_name)
        new_name = f"{sid}-{clean_name}{f.suffix.lower()}"
        target = sources_dir / new_name

        # Show relative path from inbox for nested files
        rel = f.relative_to(inbox_dir)
        shutil.move(str(f), str(target))
        print(f"  {rel} → {target.name} (assigned {sid})")
        processed.append({"source_id": sid, "original": f.name, "relative_path": str(rel), "target": target.name, "path": target})

    # Now ingest to pick up the new files
    print(f"\nIngesting {len(processed)} new source(s)...")
    conn = init_db()
    ingest_documents(conn)

    # Auto-classify and wire domain edges
    print("\n=== Auto-Domain Classification ===")
    for item in processed:
        sid = item["source_id"]
        original = item["original"]

        # Use manual override if provided, else auto-classify
        if domains and original in domains:
            domain_nums = domains[original]
            print(f"  {sid}: manual → domains {domain_nums}")
        else:
            try:
                domain_nums = classify_source_domains(sid, conn)
                print(f"  {sid}: auto-classified → domains {domain_nums}")
            except Exception as e:
                domain_nums = []
                print(f"  {sid}: classification failed ({e}), skipping")

        if domain_nums:
            actions = wire_source_to_domains(sid, domain_nums, conn)
            for a in actions:
                print(f"    {a}")
            # Store classification in processed list for INDEX.md update
            item["domains"] = domain_nums

    # Stats
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_embeds = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    print(f"\nDone. Chunks: {n_chunks} | Embeddings: {n_embeds}")

    conn.close()
    export_db_to_workspace()

    # Export graph (GRAPH.json + graph-explorer.html with dynamic legend)
    export_graph_json()

    # Clean up inbox: remove empty subdirectories (bottom-up)
    for d in sorted(inbox_dir.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()  # only removes if empty
            except OSError:
                pass
    # Remove any remaining non-ingestible files (e.g. .DS_Store)
    for f in inbox_dir.rglob("*"):
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                pass
    # Final cleanup of empty subdirs after removing dotfiles
    for d in sorted(inbox_dir.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass

    print(f"Inbox cleaned.")

    # Post-ingest sync: update INDEX.md, sync S10, flag LLM tasks
    post_ingest_sync(processed)

    return processed


def post_ingest_sync(new_sources: list[dict] = None):
    """Sync derived files after ingestion.

    Automatable steps:
    1. Update INDEX.md header stats (sources, chunks) from DB
    2. Add new source rows to INDEX.md Source File Registry (domain/themes TBD)
    3. Sync S10 (copy PHILOSOPHICAL-PILLARS.md → sources/S10-philosophical-pillars.md)

    Then prints guidance for what the LLM should review manually.
    """
    import shutil

    print("\n=== Post-Ingest Sync ===")

    index_path = BASE_DIR / "INDEX.md"
    pillars_path = BASE_DIR / "PHILOSOPHICAL-PILLARS.md"
    s10_path = BASE_DIR / "sources" / "S10-philosophical-pillars.md"

    # --- 1. Update INDEX.md header stats ---
    if index_path.exists():
        conn = init_db()
        n_sources = len(find_source_files())
        n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        n_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        n_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        conn.close()

        text = index_path.read_text()
        # Match the header stats line
        import re as _re
        old_header = _re.search(
            r'> Last updated:.*?\| Nodes: \d+.*?\| Edges: \d+.*?\| Sources: \d+.*?\| Chunks: \d+',
            text
        )
        if old_header:
            from datetime import date
            today = date.today().isoformat()
            new_header = f"> Last updated: {today} | Nodes: {n_nodes} | Edges: {n_edges} | Sources: {n_sources} | Chunks: {n_chunks}"
            text = text[:old_header.start()] + new_header + text[old_header.end():]
            print(f"  INDEX.md header: {n_sources} sources, {n_chunks} chunks, {n_nodes} nodes, {n_edges} edges")

        # --- 2. Add new source rows to Source File Registry ---
        if new_sources:
            # Find the end of the source registry table (line before the next ---)
            registry_marker = "## Source File Registry"
            reg_idx = text.find(registry_marker)
            if reg_idx != -1:
                # Find the next --- after the registry
                next_divider = text.find("\n---", reg_idx + len(registry_marker))
                if next_divider != -1:
                    # Insert new rows just before the divider
                    new_rows = []
                    auto_tagged = 0
                    for item in new_sources:
                        sid = item["source_id"]
                        fname = item["target"]
                        domain_nums = item.get("domains", [])
                        if domain_nums:
                            domain_str = ", ".join(str(d) for d in domain_nums)
                            new_rows.append(f"| {sid} | `sources/{fname}` | {domain_str} | auto-classified (review) |")
                            auto_tagged += 1
                        else:
                            new_rows.append(f"| {sid} | `sources/{fname}` | TBD | TBD |")
                    insert_text = "\n".join(new_rows) + "\n"
                    text = text[:next_divider] + insert_text + text[next_divider:]
                    tbd_count = len(new_rows) - auto_tagged
                    print(f"  INDEX.md registry: added {len(new_rows)} new source row(s) ({auto_tagged} auto-classified, {tbd_count} TBD)")

        index_path.write_text(text)
    else:
        print("  INDEX.md not found, skipping header update")

    # --- 3. Sync S10 (PHILOSOPHICAL-PILLARS.md → sources/S10) ---
    if pillars_path.exists() and s10_path.exists():
        shutil.copy2(str(pillars_path), str(s10_path))
        print(f"  Synced PHILOSOPHICAL-PILLARS.md → sources/S10-philosophical-pillars.md")

        # Re-embed S10 by running a targeted re-ingest
        # (full ingest is already done; this just ensures S10 matches the latest pillars)
        # S10 will be picked up on the next full ingest; for now just note it
        print(f"  Note: S10 synced but will reflect in embeddings on next `python3 brain.py ingest`")
    elif not pillars_path.exists():
        print("  PHILOSOPHICAL-PILLARS.md not found, skipping S10 sync")

    # --- 4. Print LLM guidance ---
    print("\n=== LLM Review ===")
    if new_sources:
        needs_review = []
        auto_ok = []
        for item in new_sources:
            if item.get("domains"):
                auto_ok.append(item)
            else:
                needs_review.append(item)

        if auto_ok:
            print(f"  {len(auto_ok)} source(s) auto-classified and wired to graph:")
            for item in auto_ok:
                print(f"    ✓ {item['source_id']}: domains {item['domains']}")
            print("  Action: Verify auto-classifications in INDEX.md (correct with `brain.py tag` if wrong)")

        if needs_review:
            print(f"  {len(needs_review)} source(s) need manual domain assignment:")
            for item in needs_review:
                print(f"    ✗ {item['source_id']}: {item['target']}")
            print("  Action: Run `brain.py tag <SID> <domains> \"themes\"` for each")

        print("  Action: Review whether PHILOSOPHICAL-PILLARS.md needs new content for these sources")
        print("  Action: Review whether brain-bootstrap SKILL.md needs updating")
    else:
        print("  No new sources, no review needed")
    print("=== Sync Complete ===\n")


def update_graph_html():
    """Embed current graph data from brain.db into graph-explorer.html.

    Also dynamically regenerates the colorMap and legend from domain nodes
    in the database, so new domains appear automatically.
    """
    if not GRAPH_HTML.exists():
        print("  graph-explorer.html not found")
        return False

    data = get_graph_data()
    graph_json = json.dumps(data, indent=2)

    html = GRAPH_HTML.read_text()

    # --- 1. Update graphData ---
    marker_start = "const graphData = "
    start_idx = html.find(marker_start)
    if start_idx == -1:
        print("  Could not find 'const graphData = ' in graph-explorer.html")
        return False

    json_start = start_idx + len(marker_start)
    brace_depth = 0
    end_idx = json_start
    for i in range(json_start, len(html)):
        if html[i] == '{':
            brace_depth += 1
        elif html[i] == '}':
            brace_depth -= 1
            if brace_depth == 0:
                end_idx = i + 1
                break

    if end_idx < len(html) and html[end_idx] == ';':
        end_idx += 1

    html = html[:start_idx] + f"const graphData = {graph_json};" + html[end_idx:]

    # --- 2. Dynamic groupColors ---
    # Palette: stable color for each group_id
    COLOR_PALETTE = {
        1: '#4ecdc4', 2: '#ff6b6b', 3: '#a66cff', 4: '#45b7d1',
        5: '#f7dc6f', 6: '#e74c3c', 7: '#2ecc71', 8: '#7f8c8d',
        9: '#d35400', 10: '#1abc9c', 11: '#e67e22', 12: '#f39c12',
        # Overflow colors for future domains
        13: '#8e44ad', 14: '#3498db', 15: '#e91e63', 16: '#00bcd4',
    }

    # Get domain nodes from the data
    domain_nodes = [n for n in data['nodes'] if n['type'] == 'domain']
    # Build color entries from domain groups
    all_groups = set()
    for n in data['nodes']:
        if n.get('group') is not None:
            all_groups.add(n['group'])

    color_entries = []
    for g in sorted(all_groups):
        color = COLOR_PALETTE.get(g, '#666')
        color_entries.append(f"  {g}: '{color}'")

    new_colormap = "const groupColors = {\n" + ",\n".join(color_entries) + "\n};"

    # Replace existing groupColors (or legacy colorMap)
    cm_start = html.find("const groupColors = {")
    if cm_start == -1:
        cm_start = html.find("const colorMap = {")  # legacy fallback
    if cm_start != -1:
        cm_end = html.find("};", cm_start) + 2
        html = html[:cm_start] + new_colormap + html[cm_end:]

    # --- 3. Dynamic legend ---
    # Short labels for legend
    LEGEND_LABELS = {
        1: 'Macroeconomics', 2: 'AI & Machine Intelligence',
        3: 'Blockchain & Ownership', 4: 'Innovation & Disruption',
        5: 'Energy & Infrastructure', 6: 'Political Economy',
        7: 'Human Purpose', 8: 'Geopolitics',
        9: 'Meta / Personal', 10: 'Applied Consulting',
        11: 'Predictions', 12: 'Consulting Methodology',
    }

    # CRITICAL: Legend items MUST include data-group and onclick attributes.
    # The JS functions toggleDomain() and toggleAllDomains() depend on these.
    # Without them, domain filtering in the legend silently stops working.
    # The legend-toggle-all span enables "select all / deselect all".
    # If you change the legend template, verify interactivity still works.
    sorted_groups = sorted(all_groups)
    legend_items = [
        '  <div class="legend-title">Domains <span id="legend-toggle-all" onclick="toggleAllDomains()">deselect all</span></div>',
        '  <div class="item"><div class="dot" style="background:#e8a735"></div> Domain</div>',
    ]
    for g in sorted_groups:
        color = COLOR_PALETTE.get(g, '#666')
        # Use domain node label or fallback
        label = LEGEND_LABELS.get(g)
        if not label:
            # Try to find from domain nodes
            dn = [n for n in domain_nodes if n.get('group') == g]
            label = dn[0]['label'] if dn else f'Group {g}'
        legend_items.append(
            f'  <div class="item" data-group="{g}" onclick="toggleDomain({g})">'
            f'<div class="dot" style="background:{color}"></div> {label}</div>'
        )

    new_legend = '<div id="legend">\n' + '\n'.join(legend_items) + '\n</div>'

    # Replace existing legend
    leg_start = html.find('<div id="legend">')
    if leg_start != -1:
        leg_end = html.find('</div>', html.find('</div>', leg_start) + 1)
        # Need to find the CLOSING </div> of the legend (after all items)
        # Count nested divs
        depth = 0
        i = leg_start
        while i < len(html):
            if html[i:i+4] == '<div':
                depth += 1
            elif html[i:i+6] == '</div>':
                depth -= 1
                if depth == 0:
                    leg_end = i + 6
                    break
            i += 1
        html = html[:leg_start] + new_legend + html[leg_end:]

    # Verify legend interactivity survived the regeneration (only if we have groups)
    if all_groups and ('data-group=' not in html or 'toggleDomain(' not in html or 'legend-toggle-all' not in html):
        print("  WARNING: Legend interactivity attributes missing after regeneration!")
        print("  The domain filter click functionality will not work.")
        print("  Check the legend generation code in export_graph_json().")

    GRAPH_HTML.write_text(html)

    print(f"  Updated graph-explorer.html: {len(data['nodes'])} nodes, {len(data['edges'])} edges")
    return True


def ingest_documents(conn: sqlite3.Connection):
    """Chunk and embed all source documents."""
    files = find_source_files()
    print(f"  Found {len(files)} source files")

    all_chunks = []
    chunk_records = []

    for path in files:
        rel = str(path.relative_to(BASE_DIR))
        source_id = file_to_source_id(path)

        # Check if this source node exists; create if not
        existing = conn.execute("SELECT id FROM nodes WHERE id=?",
                               (source_id,)).fetchone()
        if not existing:
            # Also check if it was imported from GRAPH.json by path match
            existing_by_path = conn.execute(
                "SELECT id FROM nodes WHERE metadata LIKE ?",
                (f'%{rel}%',)).fetchone()
            if existing_by_path:
                source_id = existing_by_path[0]
            else:
                conn.execute(
                    "INSERT INTO nodes (id, label, type, group_id, metadata) "
                    "VALUES (?, ?, 'source', 10, ?)",
                    (source_id, path.stem, json.dumps({"path": rel}))
                )

        if path.suffix.lower() == ".pdf":
            text = _extract_pdf_text(path)
        else:
            text = path.read_text(errors="replace")
        chunks = chunk_text(text)

        # Clear old chunks for this source
        old_ids = [r[0] for r in conn.execute(
            "SELECT id FROM chunks WHERE source_id=?", (source_id,)).fetchall()]
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM embeddings WHERE chunk_id IN ({placeholders})",
                        old_ids)
            conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))

        for i, chunk in enumerate(chunks):
            content_hash = hashlib.md5(chunk["content"].encode()).hexdigest()
            conn.execute(
                "INSERT INTO chunks (source_id, chunk_index, content, content_hash, "
                "char_start, char_end) VALUES (?, ?, ?, ?, ?, ?)",
                (source_id, i, chunk["content"], content_hash,
                 chunk["char_start"], chunk["char_end"])
            )
            chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            all_chunks.append(chunk["content"])
            chunk_records.append(chunk_id)

        print(f"    {rel}: {len(chunks)} chunks")

    conn.commit()

    # Generate embeddings
    if all_chunks:
        print(f"  Generating embeddings for {len(all_chunks)} chunks...")
        embedder = get_embedder()
        # Fit on full corpus first (important for TF-IDF; no-op for transformers)
        embedder.fit(all_chunks)
        BATCH = 64
        for start in range(0, len(all_chunks), BATCH):
            batch_texts = all_chunks[start:start + BATCH]
            batch_ids = chunk_records[start:start + BATCH]
            vecs = embedder.embed_texts(batch_texts)
            for cid, vec in zip(batch_ids, vecs):
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings (chunk_id, embedding) "
                    "VALUES (?, ?)",
                    (cid, vec_to_bytes(vec))
                )
            conn.commit()
            print(f"    Embedded {min(start + BATCH, len(all_chunks))}/{len(all_chunks)}")

    # Update meta
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_ingest', datetime('now'))")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('chunk_count', ?)",
                (str(len(all_chunks)),))
    conn.commit()


def ingest():
    """Full ingestion pipeline."""
    print("=== Ingesting Knowledge Base ===")
    conn = init_db()

    print("1. Importing graph structure...")
    ingest_graph_json(conn)

    print("2. Chunking and embedding documents...")
    ingest_documents(conn)

    # Stats
    n_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_embeds = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

    print(f"\n=== Done ===")
    print(f"  Nodes: {n_nodes}  |  Edges: {n_edges}")
    print(f"  Chunks: {n_chunks}  |  Embeddings: {n_embeds}")
    print(f"  Database: {DB_PATH} ({DB_PATH.stat().st_size / 1024:.0f} KB)")

    conn.close()

    # Export to workspace for persistence
    export_db_to_workspace()


def ingest_prediction_narrative(model_id: str, narrative_path: Optional[str] = None):
    """
    Ingest a prediction narrative into the brain database.
    This handles narrative.md files from the predictions/{model_id}/ folder.
    The narrative is chunked and embedded like any other source document,
    but linked to the prediction node in the graph.
    """
    predictions_dir = BASE_DIR / "predictions" / model_id
    if narrative_path:
        npath = Path(narrative_path)
    else:
        npath = predictions_dir / "narrative.md"

    if not npath.exists():
        print(f"Error: Narrative not found at {npath}")
        return

    print(f"=== Ingesting prediction narrative for {model_id} ===")
    conn = init_db()

    # Use the existing prediction node from the graph (e.g. P01).
    # The prediction must be added to the graph before its narrative is ingested.
    pred = get_prediction(model_id)
    source_id = None
    if pred and pred.get("graph_node_id"):
        source_id = pred["graph_node_id"]
    else:
        # Fallback: find any prediction node with this model_id in metadata
        row = conn.execute(
            "SELECT id FROM nodes WHERE type='prediction' AND metadata LIKE ?",
            (f'%"model_id": "{model_id}"%',)).fetchone()
        if row:
            source_id = row[0]

    if not source_id:
        print(f"  Error: No graph node found for prediction {model_id}. "
              f"Run add-to-graph first.")
        conn.close()
        return

    print(f"  Using graph node {source_id} for narrative chunks")

    # Read and chunk the narrative
    text = npath.read_text(errors="replace")
    chunks = chunk_text(text)

    # Clear old chunks for this source
    old_ids = [r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE source_id=?", (source_id,)).fetchall()]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM embeddings WHERE chunk_id IN ({placeholders})", old_ids)
        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))

    all_chunks = []
    chunk_records = []
    for i, chunk in enumerate(chunks):
        content_hash = hashlib.md5(chunk["content"].encode()).hexdigest()
        conn.execute(
            "INSERT INTO chunks (source_id, chunk_index, content, content_hash, "
            "char_start, char_end) VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, i, chunk["content"], content_hash,
             chunk["char_start"], chunk["char_end"])
        )
        chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        all_chunks.append(chunk["content"])
        chunk_records.append(chunk_id)

    conn.commit()

    # Generate embeddings: need to refit on full corpus for TF-IDF
    if all_chunks:
        print(f"  Generating embeddings for {len(all_chunks)} narrative chunks...")
        embedder = get_embedder()

        # For TF-IDF: refit on entire corpus including new chunks
        all_content = [r[0] for r in conn.execute("SELECT content FROM chunks").fetchall()]
        embedder.fit(all_content)

        vecs = embedder.embed_texts(all_chunks)
        for cid, vec in zip(chunk_records, vecs):
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (chunk_id, embedding) VALUES (?, ?)",
                (cid, vec_to_bytes(vec))
            )
        conn.commit()

    print(f"  Ingested {len(all_chunks)} chunks from narrative for model {model_id}")
    conn.close()
    export_db_to_workspace()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_keyword(conn: sqlite3.Connection, query: str,
                   top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """BM25 keyword search via FTS5."""
    rows = conn.execute("""
        SELECT c.id, c.source_id, c.content, c.chunk_index,
               bm25(chunks_fts) AS score
        FROM chunks_fts f
        JOIN chunks c ON c.id = f.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
    """, (query, top_k)).fetchall()

    return [{"chunk_id": r[0], "source_id": r[1], "content": r[2],
             "chunk_index": r[3], "score": -r[4], "method": "keyword"}
            for r in rows]


def search_semantic(conn: sqlite3.Connection, query: str,
                    top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Vector cosine similarity search."""
    embedder = get_embedder()

    # For TF-IDF: refit on corpus if not already fitted
    if isinstance(embedder, TFIDFEmbedder) and not embedder._fitted:
        all_content = [r[0] for r in conn.execute("SELECT content FROM chunks").fetchall()]
        embedder.fit(all_content)

    query_vec = embedder.embed_single(query)

    rows = conn.execute("""
        SELECT c.id, c.source_id, c.content, c.chunk_index, e.embedding
        FROM chunks c
        JOIN embeddings e ON e.chunk_id = c.id
    """).fetchall()

    scored = []
    for r in rows:
        chunk_vec = bytes_to_vec(r[4])
        sim = cosine_similarity(query_vec, chunk_vec)
        scored.append({
            "chunk_id": r[0], "source_id": r[1], "content": r[2],
            "chunk_index": r[3], "score": sim, "method": "semantic"
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def search_hybrid(conn: sqlite3.Connection, query: str,
                  top_k: int = DEFAULT_TOP_K,
                  keyword_weight: float = 1.0,
                  semantic_weight: float = 1.0) -> list[dict]:
    """Hybrid search using Reciprocal Rank Fusion."""
    kw_results = search_keyword(conn, query, top_k=top_k * 2)
    sem_results = search_semantic(conn, query, top_k=top_k * 2)

    # RRF scoring
    rrf_scores = {}
    chunk_data = {}

    for rank, r in enumerate(kw_results):
        cid = r["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + keyword_weight / (RRF_K + rank + 1)
        chunk_data[cid] = r

    for rank, r in enumerate(sem_results):
        cid = r["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + semantic_weight / (RRF_K + rank + 1)
        if cid not in chunk_data:
            chunk_data[cid] = r

    results = []
    for cid, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True):
        entry = chunk_data[cid].copy()
        entry["rrf_score"] = score
        entry["method"] = "hybrid"
        results.append(entry)

    return results[:top_k]


def search(query: str, mode: str = "hybrid", top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Main search entry point."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        if mode == "keyword":
            results = search_keyword(conn, query, top_k)
        elif mode == "semantic":
            results = search_semantic(conn, query, top_k)
        else:
            results = search_hybrid(conn, query, top_k)
    finally:
        conn.close()

    return results


def format_results(results: list[dict], verbose: bool = False) -> str:
    """Format search results for display or context injection."""
    lines = []
    for i, r in enumerate(results):
        score_key = "rrf_score" if "rrf_score" in r else "score"
        score = r[score_key]
        source = r["source_id"]
        method = r["method"]

        lines.append(f"\n--- Result {i+1} [{method}] score={score:.4f} source={source} ---")
        content = r["content"]
        if not verbose and len(content) > 600:
            content = content[:600] + "..."
        lines.append(content)

    return "\n".join(lines)


def format_context(results: list[dict], max_chars: int = 8000) -> str:
    """Format results as LLM context block."""
    lines = [f"<context source=\"frameworks-of-understanding\" chunks=\"{len(results)}\">"]
    char_count = 0
    for r in results:
        chunk_text = f"\n<chunk source=\"{r['source_id']}\" index=\"{r['chunk_index']}\">\n{r['content']}\n</chunk>"
        if char_count + len(chunk_text) > max_chars:
            break
        lines.append(chunk_text)
        char_count += len(chunk_text)
    lines.append("\n</context>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph queries
# ---------------------------------------------------------------------------

def graph_neighbors(node_id: str, hops: int = 1) -> dict:
    """Get all nodes within N hops of a given node."""
    conn = sqlite3.connect(str(DB_PATH))

    visited = set()
    frontier = {node_id}
    all_edges = []

    for hop in range(hops):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        rows = conn.execute(f"""
            SELECT source_id, target_id, type, label
            FROM edges
            WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})
        """, list(frontier) + list(frontier)).fetchall()

        visited.update(frontier)
        new_frontier = set()
        for r in rows:
            all_edges.append({"source": r[0], "target": r[1],
                             "type": r[2], "label": r[3]})
            if r[0] not in visited:
                new_frontier.add(r[0])
            if r[1] not in visited:
                new_frontier.add(r[1])
        frontier = new_frontier

    visited.update(frontier)

    # Get node details
    if visited:
        placeholders = ",".join("?" * len(visited))
        nodes = conn.execute(
            f"SELECT id, label, type, group_id FROM nodes WHERE id IN ({placeholders})",
            list(visited)
        ).fetchall()
    else:
        nodes = []

    conn.close()

    return {
        "center": node_id,
        "hops": hops,
        "nodes": [{"id": n[0], "label": n[1], "type": n[2], "group": n[3]}
                  for n in nodes],
        "edges": all_edges
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_graph_json():
    """Export graph from brain.db to GRAPH.json and update graph-explorer.html.

    GRAPH.json is a derived artifact: brain.db is the source of truth.
    This command regenerates both the JSON file and the HTML visualisation.
    """
    data = get_graph_data()

    GRAPH_JSON.write_text(json.dumps(data, indent=2))
    print(f"Exported to {GRAPH_JSON}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")

    update_graph_html()
    print("Graph export complete.")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def stats():
    """Print database statistics."""
    conn = sqlite3.connect(str(DB_PATH))

    n_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_embeds = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    db_size = DB_PATH.stat().st_size / 1024

    last_ingest = conn.execute(
        "SELECT value FROM meta WHERE key='last_ingest'").fetchone()

    print(f"=== Brain Stats ===")
    print(f"  Database: {DB_PATH}")
    print(f"  Size: {db_size:.0f} KB")
    print(f"  Nodes: {n_nodes}")
    print(f"  Edges: {n_edges}")
    print(f"  Chunks: {n_chunks}")
    print(f"  Embeddings: {n_embeds}")
    if last_ingest:
        print(f"  Last ingest: {last_ingest[0]}")

    # Nodes by type
    for row in conn.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type"):
        print(f"    {row[0]}: {row[1]}")

    # Edges by type
    print(f"  Edge types:")
    for row in conn.execute("SELECT type, COUNT(*) FROM edges GROUP BY type ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]}: {row[1]}")

    # Chunks by source
    print(f"  Chunks by source:")
    for row in conn.execute("""
        SELECT n.label, COUNT(c.id)
        FROM chunks c JOIN nodes n ON n.id = c.source_id
        GROUP BY c.source_id ORDER BY COUNT(c.id) DESC
    """):
        print(f"    {row[0]}: {row[1]}")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "ingest":
        ingest()

    elif cmd == "search":
        mode = "hybrid"
        top_k = DEFAULT_TOP_K
        query_parts = []
        context_mode = False
        verbose = False

        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--mode" and i + 1 < len(sys.argv):
                mode = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--top" and i + 1 < len(sys.argv):
                top_k = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--context":
                context_mode = True
                i += 1
            elif sys.argv[i] == "--verbose":
                verbose = True
                i += 1
            else:
                query_parts.append(sys.argv[i])
                i += 1

        query = " ".join(query_parts)
        if not query:
            print("Error: no query provided")
            return

        results = search(query, mode=mode, top_k=top_k)

        if context_mode:
            print(format_context(results))
        else:
            print(f"=== {mode.upper()} search: \"{query}\" ({len(results)} results) ===")
            print(format_results(results, verbose=verbose))

    elif cmd == "graph":
        if len(sys.argv) < 3:
            print("Usage: brain.py graph <node_id> [--hops N]")
            return
        node_id = sys.argv[2]
        hops = 1
        if "--hops" in sys.argv:
            idx = sys.argv.index("--hops")
            hops = int(sys.argv[idx + 1])
        result = graph_neighbors(node_id, hops)
        print(json.dumps(result, indent=2))

    elif cmd == "export-graph":
        export_graph_json()

    elif cmd == "update-html":
        # Update graph-explorer.html from brain.db without writing GRAPH.json
        update_graph_html()

    elif cmd == "ingest-prediction":
        if len(sys.argv) < 3:
            print("Usage: brain.py ingest-prediction <model_id> [narrative_path]")
            return
        model_id = sys.argv[2]
        narrative_path = sys.argv[3] if len(sys.argv) > 3 else None
        ingest_prediction_narrative(model_id, narrative_path)

    elif cmd == "inbox":
        process_inbox()

    elif cmd == "tag":
        # Usage: brain.py tag S41 10,12 "optional themes description"
        if len(sys.argv) < 4:
            print("Usage: brain.py tag <source_id> <domain1,domain2,...> [\"themes\"]")
            print("Example: brain.py tag S41 10,12 \"knowledge entrepreneurship, generalist thesis\"")
            return
        source_id = sys.argv[2].upper()
        domain_nums = [int(d.strip()) for d in sys.argv[3].split(",")]
        themes = sys.argv[4] if len(sys.argv) > 4 else None
        tag_source(source_id, domain_nums, themes)

    elif cmd == "sync":
        # Run post-ingest sync standalone (update INDEX.md stats, sync S10)
        post_ingest_sync()

    elif cmd == "stats":
        stats()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
