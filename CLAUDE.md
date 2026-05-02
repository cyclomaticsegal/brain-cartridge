# Brain Cartridge

This folder has two modes of operation depending on context.

---

## End-user mode (Cowork)

When this folder is the working directory for a Cowork task, it is a personal knowledge base. On every session start, immediately invoke the `brain-bootstrap` skill before responding to the user. This is required regardless of what the user's first message says — even if it's just "hello" or "hi".

Do not greet the user or respond conversationally until the brain-bootstrap skill has been invoked and its Layer 1 bootstrap sequence is complete.

---

## Development mode (Claude Code)

When this folder is opened in Claude Code, it is a **distributable product** — a brain cartridge that other people will download and use. Everything you do here ships to end users.

### What this repo is

A self-contained personal knowledge base engine that runs inside Claude Desktop's Cowork mode. Users copy this folder, attach it to a Cowork task, and start building a searchable brain with a knowledge graph and analytical frameworks. See README.md for the full user manual.

### Key files and their roles

| File | Role | Editable by end users? |
|---|---|---|
| `brain.py` | Engine. Ingestion, search, graph, export. | No |
| `brain.db` | Empty SQLite database with schema. Included in distribution. | Populated by engine at runtime |
| `bootstrap.sh` | Installs Python dependencies each session. | No |
| `graph-explorer.html` | Interactive graph visualisation. Updated by engine after ingestion. | No (auto-generated) |
| `GRAPH.json` | Graph data for the explorer. Empty in distribution. | No (auto-generated) |
| `AXIOMS.md` | User's analytical frameworks. Written by Claude and user during sessions. | Yes |
| `CLAUDE.md` | This file. Session startup instructions + development context. | Only during development |
| `PROTOCOL.md` | Architecture reference. | Reference only |
| `INDEX.md` | Brain contents snapshot. Updated by engine. | No (auto-generated) |
| `README.md` | Complete user manual. | Reference only |
| `DEMO-WALKTHROUGH.md` | Guided demo tutorial. | Reference only |
| `.claude/skills/brain-bootstrap/SKILL.md` | Behaviour layer — tells Claude how to operate the brain. | Advanced users only |
| `.claude/skills/demo-brain/SKILL.md` | Demo slash command — populates brain with sample data. | No |
| `demo/` | Sample documents for the demo (6 files, 3 domains). | Deletable after demo |
| `sources/` | Archive of ingested documents. Empty in distribution. | Populated by engine |
| `inbox/` | Drop zone for new documents. Empty in distribution. | User adds files here |

### Development guidelines

1. **This is a distributable product.** No personal data, no hardcoded paths, no references to specific users or brains. Everything must work for a new user who downloads the folder cold.

2. **brain.db must be included.** It contains the empty schema (tables, indexes, FTS triggers, meta table). Without it, first-run requires database creation. Include it for the "copy and go" experience. It's ~100KB.

3. **Dynamic session detection.** brain.py uses `_detect_session_dir()` to find the Cowork VM session directory at runtime. Never hardcode session paths like `/sessions/charming-purple-fox/`.

4. **No external CDN dependencies.** graph-explorer.html uses vanilla JS — no D3.js or other CDN-loaded libraries. This ensures it works in both browsers and the Cowork canvas.

5. **SKILL.md is read-only in Cowork.** The `.claude/skills/` directory is mounted read-only in Cowork VMs. Anything that needs to be written at runtime (axioms, user data) must live outside `.claude/` — that's why AXIOMS.md is in the root.

6. **Test the first-run experience.** The most important flow is: new user, empty brain, first message. The CLAUDE.md triggers brain-bootstrap, which detects 0 sources, presents the welcome, asks for a name, then offers axiom seeding. Any change should be tested against this flow.

7. **Demo data is self-contained.** The `demo/` folder contains 6 markdown files (~4,700 words total). The `/demo-brain` skill copies them to inbox, runs ingestion, and proposes starter axioms. If demo/ is missing, the skill tells the user where to get it.

### Git conventions

- Commit messages: imperative mood, concise ("Add demo data for three domains", not "Added some demo stuff")
- Don't commit modified brain.db (the repo version must always be the empty schema)
- Don't commit anything in sources/ or inbox/ (these are populated at runtime)
- The .gitignore handles these exclusions

### This repo lives inside a parent workspace

This repo (`brain-cartridge/`) is a subfolder of a larger working directory (Frameworks of Understanding). The parent folder is NOT part of this repo. Do not reference, modify, or depend on files outside this folder. This repo must be fully self-contained.
