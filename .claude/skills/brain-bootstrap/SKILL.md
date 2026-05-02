---
name: brain-bootstrap
description: "Personal knowledge base engine. This skill MUST trigger on the very first message in any new session — regardless of what the user says, including greetings like 'hello', 'hi', 'what is this', 'help', 'get started', or any casual opener. It must also trigger on any substantive task: analysing a topic, evaluating a claim, forming a strategy, assessing a market, writing about any domain the user has ingested material on, or any question where the user's accumulated knowledge base would sharpen the answer. Also triggers on all brain-specific operations: brain, brain.py, search my brain, ingest, knowledge base search, hybrid search, RAG, knowledge graph, export-graph, or any reference to querying the knowledge base. When in doubt, trigger — the bootstrap is idempotent."
---

# Personal Knowledge Base — Brain Operating System

This skill has three layers. Execute them in order.

---

## Layer 1: Bootstrap

The Cowork VM resets between sessions, wiping all pip-installed packages. Before any brain.py operation, run the bootstrap script:

```bash
bash /sessions/<session-name>/mnt/<workspace-folder>/bootstrap.sh
```

Replace `<session-name>` with the current session path from the system prompt (e.g. `charming-purple-fox`). Replace `<workspace-folder>` with the name of the working folder as it appears in the mount path. This takes ~30 seconds and is idempotent.

After bootstrap, the brain database (`brain.db`) auto-restores from the workspace — searches work immediately without re-ingesting.

### First-run detection

After running bootstrap, check whether the brain is empty:

```bash
python3 /sessions/<session-name>/mnt/<workspace-folder>/brain.py stats
```

If the output shows **0 sources and 0 nodes**, this is a fresh brain that has never been used. In that case, **ignore the user's message for now** and instead present a welcome message:

> **Welcome to your personal knowledge base.**
>
> Your brain is set up and ready, but it's empty — there's nothing in it yet. Here's how to get started:
>
> 1. **Add material.** Drop `.md`, `.txt`, or `.pdf` files into the `inbox/` folder in your working directory.
> 2. **Tell me to process them.** Say something like "process my inbox" or "ingest the new files" and I'll chunk, embed, and index everything.
> 3. **Ask me anything** about your ingested material. I'll search your brain automatically.
> 4. **Explore your knowledge graph.** Open `graph-explorer.html` in a browser to see how your knowledge connects visually.
>
> As your brain grows, you can build **axioms** — your analytical frameworks — that I'll use as my default lens for reasoning with you. The README.md in your folder has the full user manual.
>
> But first — **what would you like to call this brain?** Give it a name and I'll remember it. It can be anything: "The Workshop", "Atlas", "My Research Brain", whatever feels right.

After presenting the welcome message, **do not proceed to Layer 2 or Layer 3**. The user has no axioms yet and there is nothing to search. Wait for the user's next message.

### First-run step 1: Brain naming

When the user provides a name, store it in brain.db's meta table:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/sessions/<session-name>/mnt/<workspace-folder>/brain.db')
conn.execute(\"INSERT OR REPLACE INTO meta (key, value) VALUES ('brain_name', '<THE_NAME>')\")
conn.commit()
conn.close()
"
```

Also export the db back to the workspace so the name persists:

```bash
python3 -c "
import sys; sys.path.insert(0, '/sessions/<session-name>/mnt/<workspace-folder>')
import brain; brain.export_db_to_workspace()
"
```

Confirm the name back to the user: "Done — this brain is now called **<THE_NAME>**."

### First-run step 2: Axiom seeding

After confirming the brain name, ask the user about their analytical frameworks:

> **Now let's set up your analytical lens.**
>
> As you feed material into this brain, I'll use your frameworks to sharpen every answer. These aren't predictions or conclusions — they're the lenses you think through.
>
> **Do you already have frameworks or intellectual interests you'd like me to start with?** For example: "I think about everything through network effects and energy constraints" or "I'm interested in innovation theory and political economy."
>
> You can name as many or as few as you like. Or say "skip" and we'll let them emerge naturally as you ingest material.

If the user names frameworks:

1. For each framework, write an initial axiom entry in AXIOMS.md under "Your frameworks". Use the user's description plus general knowledge to write a 2-3 sentence lens description. Mark `Sources: (none yet)`.
2. Confirm what was added: "I've set up [N] initial frameworks in your axioms file: [list names]. These will sharpen as you ingest material. You can also edit AXIOMS.md directly any time."

If the user says "skip" or equivalent:

1. Confirm: "No problem. As you ingest material, I'll spot patterns and propose frameworks when they emerge."
2. Do not write anything to AXIOMS.md.

After this step, the first-run sequence is complete. Wait for the user's next instruction.

If stats show sources > 0, this is an existing brain. Skip the welcome message. Instead, retrieve the brain's name:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/sessions/<session-name>/mnt/<workspace-folder>/brain.db')
row = conn.execute(\"SELECT value FROM meta WHERE key='brain_name'\").fetchone()
print(row[0] if row else 'unnamed')
conn.close()
"
```

If a name exists, use it when referring to the brain throughout the session (e.g. "Searching Atlas..." rather than "Searching the brain..."). If no name has been set, refer to it simply as "the brain" and proceed normally.

---

## Layer 2: Operating Axioms

The user's analytical frameworks live in a separate file: `AXIOMS.md` in the workspace root. This file is writable by both Claude and the user.

**At the start of every session** (after bootstrap), read the axioms file:

```bash
cat /sessions/<session-name>/mnt/<workspace-folder>/AXIOMS.md
```

If the file has content under "Your frameworks", load those frameworks into working context. They are the default analytical lens for any substantive question. When answering, apply these lenses and cite which frameworks informed the reasoning.

If the file has no user-added frameworks yet (only the template), proceed without axioms. The brain still works — it just doesn't have a personalised analytical lens yet.

### Building axioms: two paths

**Top-down (user declares).** The user names frameworks they think through. Claude writes initial axiom entries in AXIOMS.md based on the user's description and general knowledge. These get refined as material is ingested that deepens the framework.

**Bottom-up (patterns emerge).** During or after ingestion, if a theme or framework appears across three or more sources, Claude proposes a new axiom:

> "Your material keeps returning to [theme] across [domains]. Want me to add a [framework name] axiom to your frameworks?"

The user approves, refines, or rejects. **Claude never adds axioms without explicit user agreement.**

### Writing axiom entries

Each axiom entry in AXIOMS.md should contain:

1. **Framework name** as a heading.
2. **The lens** — 2-3 sentences describing how to apply this framework. Not a definition of the concept, but an instruction to Claude: what to look for, what questions to ask, when this lens matters.
3. **Sources** — updated as the user ingests material relevant to this framework. Format: `Sources: S01, S05, S12` (referencing brain.db source IDs).

The axiom is a signpost. The brain holds the depth. When Claude needs detail on a framework, it searches brain.db using the axiom as the query guide.

### Axiom refinement

After every ingestion (`brain.py inbox`), review the current axioms against the newly ingested material:

1. Does any existing axiom need sharpening based on what was just ingested? If so, propose the edit.
2. Does the new material reveal a cross-source pattern that isn't captured by any existing axiom? If so, propose a new one.
3. Update the `Sources:` line on any axiom that gained relevant new material.

Always show the proposed change and wait for approval before writing to AXIOMS.md.

### Framework Purity (Ingestion Scope)

This brain contains only user-curated content. Any proposed addition must anchor to one of:

1. **Existing brain content.** Concepts, sources, or edges already in brain.db.
2. **Session input.** Text the user has introduced directly in this session with an explicit ingestion instruction.
3. **Canonical public framework.** A named intellectual framework with known author or tradition, citeable origin, and recognised position in the public intellectual record.

Four tests identify a canonical framework:
- **Name test.** Can the author, school, or specific work be named?
- **Cite test.** Can a paper, book, or widely referenced argument be pointed to?
- **Fit test.** Does it plug into the brain's existing taxonomy?
- **Recognition test.** Would the user recognise this as something in their intellectual ambit?

When uncertain, ask before proposing.

**Admissibility is not ingestion.** Canonical frameworks may be referenced in analysis without entering the brain. They become nodes in brain.db only when the user explicitly instructs ingestion.

Cross-skill context, general training knowledge, web search results, and prior session memory are never admissible as ingestion material.

---

## Layer 3: Retrieval Decision Tree

When a substantive question arrives — analysis, strategy, evaluation, writing, or anything where domain knowledge matters — choose the right retrieval method:

### 1. Use what's already in context

If a source file was read or ingested earlier in this conversation and the follow-up question is directly about that same content, use what's already in working memory. No tool call needed.

**Example:** You just read a PDF for the user. They ask a follow-up about a specific section. Use the content you already have.

### 2. Read the source file directly

If the question is about document structure (table of contents, chapter list, specific sections, page-level navigation), read the source file. RAG chunks lose document structure.

**Example:** "Give me the chapter list from that book." Read the PDF. The chunks won't reconstruct the TOC.

### 3. Search the brain (RAG)

If the question is conceptual, cross-domain, or about material not recently read in this conversation, search the brain. This is the default for any question that could draw from multiple sources or where cross-source connections matter.

```bash
BRAIN="/sessions/<session-name>/mnt/<workspace-folder>/brain.py"
python3 $BRAIN search "relevant query terms"
```

### 4. When in doubt, search the brain

RAG is the safe default. It's never wrong to search. It's occasionally unnecessary if the content is already in context, but it won't produce a bad outcome.

### Grounding and citation

Regardless of retrieval method, ground responses in the user's specific frameworks. Cite which concepts or sources informed the answer. If the search returns nothing relevant, say so and proceed with general knowledge.

For multi-faceted questions, run multiple searches with different query terms to pull from different domains.

---

## Technical Reference

### Brain Operations

```bash
BRAIN="/sessions/<session-name>/mnt/<workspace-folder>/brain.py"

# Search (primary operation — uses existing brain.db)
python3 $BRAIN search "your query here"

# Process inbox (recursive scan, assign IDs, ingest, cleanup)
python3 $BRAIN inbox

# Re-ingest all sources (rebuilds from scratch)
python3 $BRAIN ingest

# Graph query (explore connections from a node)
python3 $BRAIN graph C11 --hops 2

# Stats
python3 $BRAIN stats

# Export graph (regenerates GRAPH.json and graph-explorer.html)
python3 $BRAIN export-graph

# Update graph-explorer.html only
python3 $BRAIN update-html
```

### Graph Architecture

The knowledge graph lives exclusively in brain.db (nodes and edges tables). GRAPH.json and graph-explorer.html are derived exports — never edit them directly.

To mutate the graph programmatically:
```python
import brain
brain.add_node("C01", "New Concept", "concept", group_id=1)
brain.add_edge("C01", "D_01", "belongs_to", label="domain link")
brain.export_graph_json()  # regenerates GRAPH.json + graph-explorer.html
```

### Important Notes

- brain.db works in the session directory (FUSE can't handle SQLite WAL mode). brain.py auto-detects the session directory and restores from the workspace on import. It exports back after every write operation.
- If sentence-transformers model download fails (proxy), brain.py falls back to TF-IDF. Expected and search quality is still good.
- After ingesting new data, run `export-graph` to keep the visual explorer in sync.
- Do NOT edit GRAPH.json or graph-explorer.html directly.

### Getting Started

1. Drop documents (`.md`, `.txt`, `.pdf`) into the `inbox/` folder.
2. Run `python3 $BRAIN inbox` — this assigns source IDs, moves files to `sources/`, ingests chunks, builds embeddings, and updates the graph.
3. Run `python3 $BRAIN search "a question about your material"` to test.
4. Open `graph-explorer.html` to see your knowledge graph visually.
5. As patterns emerge, build your analytical frameworks in AXIOMS.md (see Layer 2).
