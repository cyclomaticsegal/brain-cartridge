---
name: cowork-dev-context
description: "Development context for Brain Cartridge. Read this skill BEFORE writing any code that will run inside a Cowork session. It covers the VM architecture, file system topology, rendering constraints, and testing rules that determine whether your code works or breaks at runtime. Trigger on: any modification to graph-explorer.html, brain.py, bootstrap.sh, or any new visual/interactive component. Also trigger when asked to build dashboards, UX improvements, visualisations, or any HTML/JS/CSS that will render in the Cowork canvas or a user's browser."
---

# Cowork Development Context for Brain Cartridge

You are working on a distributable product. Everything you write here ships to end users who will run it inside Claude Desktop's Cowork mode. If you don't understand the runtime environment, your code will break silently in production even if it works perfectly in your local dev context.

Read this entire document before writing any code. Not after. Before.

---

## 1. The Runtime Environment

### What Cowork Is

Cowork is a feature of the Claude Desktop app. It runs a lightweight Linux VM (Ubuntu 22) on the user's computer. Each time the user opens a Cowork task, a fresh VM spins up with a random session name (e.g. `charming-purple-fox`, `beautiful-trusting-dirac`). The VM resets completely between sessions. Every pip-installed package, every temp file, every runtime artefact is gone when the session ends.

### The File System Topology

There are two file systems that matter. Getting this wrong is the most common source of bugs.

```
/sessions/<session-name>/              <- Local VM filesystem (fast, ephemeral)
    mnt/<workspace-folder>/            <- FUSE mount of user's real folder (persistent, slow)
```

**The FUSE mount** (`/sessions/<session-name>/mnt/<workspace-folder>/`) is the user's actual folder on their real computer, mounted into the VM via FUSE. Files written here persist between sessions. This is where the brain-cartridge repo lives.

**The session directory** (`/sessions/<session-name>/`) is local to the VM. It's a real filesystem. It's fast. It resets when the session ends.

### The SQLite Problem

SQLite uses WAL (Write-Ahead Logging) mode by default. WAL mode requires filesystem features that FUSE does not support reliably. This means:

- **brain.db cannot be operated directly on the FUSE mount.** It will produce locking errors and data corruption.
- brain.py handles this automatically: it copies brain.db from the FUSE mount into the session directory on import, operates on the local copy, and exports back to the FUSE mount after every write operation.
- Any new code that touches brain.db must follow the same pattern. Never open a SQLite connection to the FUSE-mounted path directly.

### Session Detection

The session directory name is random and changes every session. brain.py uses `_detect_session_dir()` to find it at runtime by scanning `/sessions/`. Never hardcode a session path. Any code that needs the session directory must detect it dynamically.

### Bootstrap and Dependencies

The VM starts with a bare Python 3 installation. No pip packages beyond the standard library are pre-installed. `bootstrap.sh` runs at the start of every session to install:

- numpy
- scikit-learn (for TF-IDF fallback embeddings)
- sentence-transformers (primary embedder, but model download often fails behind proxy)

If your code requires additional Python packages, they must be added to bootstrap.sh. Do not assume any package is available. Do not assume sentence-transformers loaded successfully (brain.py falls back to TF-IDF automatically).

If your code requires npm packages: npm is available on the VM but packages install to `/sessions/<session-name>/.npm-global`. They will not persist between sessions. If you need a build step, it must run every session or the output must be pre-built and committed to the repo.

---

## 2. Rendering Constraints

### graph-explorer.html: The Hard Rules

graph-explorer.html is the interactive knowledge graph visualisation. It must work in two contexts:

1. **A user's web browser** (Chrome, Firefox, Safari, Edge). The user opens the file directly from their local filesystem (`file://` protocol or served locally).
2. **The Cowork canvas** (an iframe-like rendering environment inside Claude Desktop).

These constraints are non-negotiable:

**No CDN dependencies.** No D3.js from cdnjs. No Chart.js from unpkg. No Google Fonts. No external scripts, stylesheets, or resources of any kind. The file must be fully self-contained. If you need a library, either write the functionality from scratch in vanilla JS or include the entire library source inline (and justify the file size increase).

**No ES modules or import statements.** The file runs on `file://` protocol where module loading is blocked by CORS. Everything must be in a single `<script>` block or multiple inline `<script>` blocks.

**No fetch() to local files.** `file://` protocol blocks fetch requests to other local files due to CORS. The graph data (GRAPH.json content) is embedded directly into graph-explorer.html by brain.py's `export_graph` function. It writes the JSON into a `const graphData = { ... };` declaration inside the script block.

**Single file.** graph-explorer.html is one file. No companion CSS files. No companion JS files. No image assets. Everything is inline. SVG icons, CSS, JS, data: all in one HTML file.

**No localStorage or sessionStorage.** These APIs are unreliable in the Cowork canvas context.

### How brain.py Updates graph-explorer.html

brain.py's `export_graph_json()` function does two things:

1. Writes GRAPH.json to the workspace (for external consumption).
2. Reads graph-explorer.html, finds the `const graphData = { ... };` declaration, replaces its contents with the current graph data from brain.db, and writes the updated HTML back. It also updates the legend section with current domain information.

Any changes to graph-explorer.html must preserve this injection mechanism. The `const graphData = { ... };` line must remain parseable by brain.py's regex. If you restructure the HTML, verify that `export_graph_json()` still works by running `python3 brain.py export-graph` after your changes.

### Current Rendering Approach

The current graph-explorer uses:

- **SVG** for the graph rendering (nodes as circles, edges as lines/paths)
- **Vanilla JS** for the force-directed layout simulation (custom implementation, no D3)
- **CSS** for the UI chrome (header, legend, detail panel, controls, search)

The force simulation runs its own physics: charge repulsion between nodes, spring forces on edges, centre gravity, velocity decay, and alpha cooling. It's a simplified version of D3's force simulation written from scratch.

### If You Switch to Canvas

Canvas rendering is a valid upgrade path for performance (especially with glow effects and particle systems). If you switch from SVG to Canvas:

- Mouse interaction changes: you can't attach event listeners to individual shapes. You need hit-testing (check mouse coordinates against node positions).
- Text rendering is different: Canvas text is rasterised, not selectable. Use a floating HTML div for labels if selectability matters.
- The detail panel, legend, search, and controls should remain as HTML/CSS overlays on top of the canvas. Don't render UI chrome on the canvas itself.

---

## 3. Data Architecture

### GRAPH.json Structure

```json
{
  "meta": {
    "title": "Knowledge Graph",
    "updated": "2026-05-11T10:30:00",
    "version": "2.0",
    "nodeCount": 192,
    "edgeCount": 195
  },
  "nodes": [
    {
      "id": "D_01",
      "label": "Macroeconomics & Monetary Systems",
      "type": "domain",
      "group": 1
    },
    {
      "id": "C01",
      "label": "Some Concept",
      "type": "concept",
      "group": 3,
      "sources": ["S01", "S05"]
    },
    {
      "id": "S01",
      "label": "S01: the-great-inversion",
      "type": "source",
      "group": 1
    }
  ],
  "edges": [
    {
      "source": "C01",
      "target": "D_03",
      "type": "belongs_to",
      "label": "domain link"
    }
  ]
}
```

**Node types:** `domain` (the 12 knowledge domains), `concept` (extracted ideas), `source` (ingested documents), `prediction` (optional prediction tracking).

**Edge types:** `belongs_to` (concept/source to domain), `relates_to` (concept to concept), `mentions` (source to concept), `informs` (source to prediction).

**Group IDs** correspond to domain numbers (1-12). Concepts inherit their group from their primary domain. Sources inherit from their classified domain.

### brain.db Schema (Key Tables)

```sql
-- Nodes in the knowledge graph
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    label TEXT,
    type TEXT,        -- 'domain', 'concept', 'source', 'prediction'
    group_id INTEGER  -- domain number (1-12)
);

-- Edges in the knowledge graph
CREATE TABLE edges (
    source TEXT,
    target TEXT,
    type TEXT,         -- 'belongs_to', 'relates_to', 'mentions', 'informs'
    label TEXT,
    FOREIGN KEY (source) REFERENCES nodes(id),
    FOREIGN KEY (target) REFERENCES nodes(id)
);

-- Chunk text for search
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    source_id TEXT,
    chunk_index INTEGER,
    content TEXT,
    content_hash TEXT UNIQUE
);

-- Embeddings (one per chunk)
CREATE TABLE embeddings (
    chunk_id INTEGER PRIMARY KEY,
    vector BLOB,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
);

-- Key-value metadata
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

### Adding New Data to graph-explorer.html

If you want to display additional metadata in the graph explorer (e.g. chunk counts per source, domain statistics, brain stats), you have two options:

1. **Extend the GRAPH.json meta object.** Add fields to `meta` in brain.py's `export_graph_json()`. These will be available as `graphData.meta.*` in the HTML.
2. **Add node-level metadata.** Add properties to individual node objects (e.g. `chunkCount`, `edgeCount`). These are available per-node in the JS.

Do not add a separate data-fetching mechanism. The graph explorer must work from the embedded data alone.

---

## 4. Visual Design Principles

### Current Palette

```
Background:      #0a0a0f (near-black)
Text primary:    #e0e0e0
Text secondary:  #888, #999
Text muted:      #555, #666
Accent:          #e8a735 (amber/gold)
Borders:         #222, #333
UI panels:       rgba(10,10,15,0.9) with backdrop-filter blur
```

### Domain Colours (current)

```javascript
{
  1: '#4ecdc4',  // Macroeconomics
  2: '#ff6b6b',  // AI & Machine Intelligence
  3: '#a66cff',  // Blockchain
  4: '#45b7d1',  // Innovation
  5: '#f7dc6f',  // Energy
  6: '#e74c3c',  // Political Economy
  7: '#2ecc71',  // Human Purpose
  8: '#7f8c8d',  // Geopolitics
  9: '#d35400',  // Meta / Personal
  10: '#1abc9c', // Applied Practice
  11: '#e67e22', // Predictions
  12: '#3498db', // Methodology
  13: '#9b59b6'  // Spare
}
```

### Design Direction

The visual treatment should feel like a living system, not a diagram. Reference points:

- **Space/galaxy aesthetic:** dark backgrounds, luminous nodes with glow halos, subtle particle effects. Nodes should feel like they emit light, not sit on a surface.
- **Information density:** dashboard panels around the graph showing brain stats (source count, chunk count, node/edge counts, domain breakdown). The graph is the centrepiece but the chrome provides context.
- **Variable node sizing:** node radius should scale with connection count (more edges = larger node). Domain nodes are the largest. Orphan concepts are small.
- **Smooth animation:** force simulation should feel organic. Nodes drift and settle, they don't snap. Hover effects should be subtle glows, not abrupt colour changes.

### Performance Targets

The graph must remain interactive (>30fps drag/zoom) with:
- Up to 500 nodes
- Up to 1000 edges
- Glow effects active

If canvas-based glow (shadowBlur) causes frame drops at scale, use a pre-rendered glow texture or a two-pass approach (draw glow layer at lower resolution, composite on top).

---

## 5. Testing Your Changes

### In Claude Code (development)

You can test HTML rendering by opening the file in a browser. But this only tests one of the two runtime contexts.

For graph-explorer.html specifically:

1. Run `python3 brain.py export-graph` after any structural change to verify the data injection still works.
2. Open the resulting file in a browser and verify: nodes render, edges render, drag works, zoom works, search works, legend filtering works, detail panel works.
3. Check the browser console for errors. Zero errors is the target.

### In Cowork (production)

The real test is attaching the folder to a Cowork session and verifying everything works:

1. Does bootstrap.sh complete without errors?
2. Does `brain.py stats` return correct data?
3. Does `brain.py inbox` process new files?
4. Does `brain.py export-graph` regenerate the HTML correctly?
5. Does graph-explorer.html render in a browser when opened from the workspace folder?

### What breaks silently

- **SQLite on FUSE mount:** no error message, just corrupted data or locks that never release.
- **CDN dependency in graph-explorer.html:** works in your browser with internet, fails on `file://` without internet, fails in Cowork canvas.
- **fetch() to local files:** works on localhost dev server, fails on `file://` protocol.
- **Hardcoded session paths:** works in your current session, fails in every other session.
- **Missing pip packages:** works on your machine, fails on fresh Cowork VM.

---

## 6. Files You Will Modify Most Often

| File | What it does | Regenerated? | Key constraint |
|---|---|---|---|
| graph-explorer.html | Interactive graph visualisation | Yes, by export-graph | No CDN. Single file. Data embedded inline. |
| brain.py | Engine: ingestion, search, graph, export | No | Must handle FUSE/session split. All DB ops on local copy. |
| bootstrap.sh | Installs deps each session | No | Must be idempotent. Must handle proxy failures gracefully. |
| GRAPH.json | Graph data export | Yes, by export-graph | Never edit directly. |
| SKILL.md (brain-bootstrap) | Behaviour layer for Claude in Cowork | No | Read-only in Cowork VM (.claude/skills/ is mounted read-only). |
| AXIOMS.md | User's analytical frameworks | No | Must be in repo root (not in .claude/) because it's writable at runtime. |

---

## 7. Commit Rules

- Never commit a modified brain.db. The repo version must always be the empty schema.
- Never commit anything in sources/ or inbox/. These are populated at runtime.
- If you modify graph-explorer.html, reset the graphData back to the empty state before committing:
  ```javascript
  const graphData = {
    "meta": { "title": "Knowledge Graph", "updated": "not yet", "version": "2.0", "nodeCount": 0, "edgeCount": 0 },
    "nodes": [],
    "edges": []
  };
  ```
- If you add a new Python dependency, add it to bootstrap.sh.
- Test the first-run experience after any structural change. New user, empty brain, first message. That flow must not break.
