# Operational Protocol

> How the system works, how to operate it, and where the boundaries between code and judgment sit.

**Version:** 1.0 (starter kit)

---

## System Architecture

This is a personal knowledge base with an integrated knowledge graph, hybrid search, and optional prediction capabilities. brain.db is the single source of truth for all state.

```
your-brain-folder/
├── PROTOCOL.md               <- This file (operational rules)
├── brain.py                  <- Engine: ingestion, search, graph mutations, export
├── brain.db                  <- SQLite database (graph + chunks + embeddings)
├── bootstrap.sh              <- Session initializer (installs Python deps)
│
├── graph-explorer.html       <- Projection: interactive D3.js map (auto-regenerated)
├── GRAPH.json                <- Projection: graph data for explorer (auto-regenerated)
├── INDEX.md                  <- Reference snapshot of brain contents
│
├── sources/                  <- Ingested source documents (archived after processing)
├── inbox/                    <- Drop zone for new material
│
└── .claude/
    └── skills/
        └── brain-bootstrap/
            └── SKILL.md      <- Behaviour layer: tells Claude how to operate the brain
```

### Layer Summary

| Layer | Purpose | Authoritative? |
|---|---|---|
| brain.db | Graph, chunks, embeddings, source registry, stats | Yes. Single source of truth. |
| brain.py | Engine: all operations against the database | Deterministic code. |
| SKILL.md | Tells Claude how to bootstrap, what axioms to load, when to search | Yes. User-authored behaviour layer. |
| graph-explorer.html | Interactive visualisation | No. Projection. Auto-regenerated. |
| GRAPH.json | Graph data for explorer | No. Projection. Auto-regenerated. |
| Source files | Raw ingested material | No. Archived copies. Database owns the content post-ingestion. |

**Key distinction:** Authoritative files are edited by the user or the engine. Projections are generated from the database and never edited directly. If a projection and the database disagree, the database wins and the projection is regenerated.

---

## What Is Deterministic and What Is Not

The engine (brain.py) is deterministic. Same input, same database, same results. Chunking, embedding, search ranking, classification scoring, graph mutations, export regeneration: all produce identical output every time.

The SKILL.md governs Claude's judgment: when to suggest corrections, how to synthesise search results, when to surface structural heuristics. These are non-deterministic because they involve language generation. The skill bounds the variance. It does not eliminate it.

**Rule: everything that can be code should be code.** If a behaviour can be implemented as a threshold check, a post-write hook, or a database trigger, it should not be a natural-language instruction that Claude interprets.

---

## brain.db — Single Source of Truth

All system state lives in the SQLite database.

### Tables

| Table | Purpose |
|---|---|
| nodes | Graph nodes: domains, concepts, sources, predictions |
| edges | Graph relationships (typed, labelled) |
| chunks | Document text chunks for search (with content hashes for dedup) |
| chunks_fts | FTS5 virtual table for BM25 keyword search |
| embeddings | Vectors per chunk (sentence-transformers or TF-IDF) |
| meta | Key-value store: config, stats snapshots, timestamps |
| predictions | Optional prediction tracking |

---

## Settled Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Storage | SQLite (brain.db) | Single-file, zero-config, portable |
| Search | Hybrid (BM25 + semantic, fused via RRF) | Best of keyword precision and semantic recall |
| Embeddings | sentence-transformers (primary), TF-IDF (fallback) | Graceful degradation behind proxy |
| Graph | In-database (nodes + edges tables) | No separate graph DB needed |
| Projections | GRAPH.json + graph-explorer.html | Auto-regenerated, never manually edited |
| Session handling | brain.py auto-detects Cowork VM session dir | Portable across sessions without hardcoding |
