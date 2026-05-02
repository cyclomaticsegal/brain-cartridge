---
name: demo-brain
description: "Build a demo brain with sample data to see the system in action. Use when the user says /demo-brain, 'run the demo', 'show me a demo', 'demo prism', 'try the demo', 'load demo data', or asks to see the brain working with example content."
---

# Demo Brain — Sample Data Ingestion

This skill populates the brain with sample content across three domains so the user can see the full system working: ingestion, search, knowledge graph, and axioms. It's a guided tour, not a permanent setup — the user can reset afterward and build their own brain.

---

## Step 1: Check for demo data

Check whether the `demo/` folder exists in the workspace:

```bash
ls /sessions/<session-name>/mnt/<workspace-folder>/demo/
```

Replace `<session-name>` and `<workspace-folder>` with the current session and workspace paths.

### If the demo folder is missing or empty:

Present this message and stop:

> **Demo data not found.**
>
> The `demo/` folder isn't in your working directory. This folder contains sample documents across three domains (AI & Frontier Labs, Geopolitics of AI, Energy & Compute Infrastructure) that the demo uses to populate your brain.
>
> **To get the demo data:**
> Download the `demo/` folder from the brain starter kit repository and place it in your working directory, then run `/demo-brain` again.

Do not proceed further. Wait for the user's next message.

### If the demo folder exists and contains .md files:

Continue to Step 2.

---

## Step 2: Confirm with the user

Before ingesting, present this message:

> **Ready to build your demo brain.**
>
> I found 6 sample documents in the `demo/` folder covering three domains:
>
> - **AI & Frontier Lab Economics** — scaling laws, lab competition, agents, and the application layer
> - **Geopolitics of AI** — chip supply chains, export controls, sovereign AI, and regulation
> - **Energy & Compute Infrastructure** — the energy bottleneck, data centres, grid constraints, and cooling
>
> I'll copy these into the inbox, ingest them, build the knowledge graph, and set up some starter axioms based on the content. This takes about a minute.
>
> **Note:** If you already have data in this brain, the demo content will be added alongside it. To start fresh first, say "reset" and I'll clear the brain before loading the demo.
>
> Ready to go? Say **yes** to proceed.

Wait for user confirmation before proceeding.

If the user says "reset" first, clear the brain:

```bash
python3 -c "
import sys; sys.path.insert(0, '/sessions/<session-name>/mnt/<workspace-folder>')
import brain
brain.reset_db()
brain.export_db_to_workspace()
print('Brain reset complete')
"
```

If brain.py doesn't have a `reset_db()` function, manually clear the tables:

```bash
python3 -c "
import sqlite3
db = '/sessions/<session-name>/mnt/<workspace-folder>/brain.db'
conn = sqlite3.connect(db)
for table in ['chunks', 'embeddings', 'nodes', 'edges']:
    conn.execute(f'DELETE FROM {table}')
conn.execute(\"DELETE FROM meta WHERE key != 'brain_name'\")
conn.commit()
conn.close()
print('Brain cleared (name preserved)')
"
```

Then export the cleared db back to workspace and proceed.

---

## Step 3: Copy demo files to inbox

```bash
cp /sessions/<session-name>/mnt/<workspace-folder>/demo/*.md /sessions/<session-name>/mnt/<workspace-folder>/inbox/
```

Confirm: "Copied 6 demo documents to the inbox."

---

## Step 4: Run ingestion

```bash
python3 /sessions/<session-name>/mnt/<workspace-folder>/brain.py inbox
```

This will:
1. Assign source IDs (S01-S06)
2. Move files from inbox to sources/
3. Chunk content and generate embeddings
4. Auto-classify into domains
5. Create graph nodes and edges

Report progress as it runs. When complete, report the stats:

```bash
python3 /sessions/<session-name>/mnt/<workspace-folder>/brain.py stats
```

---

## Step 5: Export the knowledge graph

```bash
python3 /sessions/<session-name>/mnt/<workspace-folder>/brain.py export-graph
```

Tell the user: "Knowledge graph built. Open `graph-explorer.html` in your browser to see it visually."

---

## Step 6: Seed starter axioms

Write three initial axioms to AXIOMS.md based on the demo content. These show the user what axioms look like in practice.

Present the proposed axioms first:

> Based on the demo content, here are three starter axioms I'd suggest:
>
> **1. Energy as Constraint** — Intelligence per unit of energy is the fundamental efficiency metric. When analysing any AI system, platform, or infrastructure investment, ask: what are the energy requirements, and do they scale? Consider Jevons' paradox — efficiency improvements tend to increase total consumption, not reduce it.
>
> **2. Supply Chain Chokepoints** — Concentrated dependencies create strategic vulnerability. When analysing any technology market, identify the chokepoints: who controls the critical nodes in the supply chain? TSMC in chips, ASML in lithography, and grid operators in power are current examples. Look for single points of failure.
>
> **3. Value Migration from Technology to Distribution** — Core technologies commoditise; value migrates to distribution, ecosystem, and switching costs. When evaluating any technology company or platform, ask: is the moat in the technology itself, or in the distribution and integration layer above it?
>
> Want me to add these to your axioms file?

If the user approves, write them to AXIOMS.md under "Your frameworks":

```bash
# Read current AXIOMS.md, find the "Add your frameworks below this line" comment,
# and insert the axiom entries after it.
```

Each axiom should follow the format in AXIOMS.md:

```markdown
### Energy as Constraint

Intelligence per unit of energy is the fundamental efficiency metric. When analysing
any AI system, platform, or infrastructure investment, ask: what are the energy
requirements, and do they scale? Consider Jevons' paradox — efficiency improvements
tend to increase total consumption, not reduce it.

Sources: S05, S06
```

Also add cross-domain bridges:

```markdown
Energy constraints shape compute supply chains — every chip needs power, and power
availability determines where AI infrastructure gets built.

Supply chain concentration amplifies geopolitical leverage — whoever controls chip
fabrication and energy supply controls the pace of AI development.

Technology commoditisation drives the scramble for distribution — as models converge
in quality, the competition shifts to infrastructure, integration, and energy access.
```

And one design principle:

```markdown
Think in systems, not variables. These three domains — AI economics, geopolitics,
and energy — are interconnected. A change in one (e.g., new chip export controls)
ripples through the others (compute availability, energy demand, lab economics).
Analyse accordingly.
```

---

## Step 7: Present the summary

After everything is complete, present a summary:

> **Your demo brain is live.** Here's what you've got:
>
> - **[N] sources** ingested across 3 domains
> - **[N] concept nodes** and **[N] edges** in the knowledge graph
> - **3 starter axioms** in your frameworks file
>
> **Things to try:**
>
> 1. **Search:** Ask me a question like "How do energy constraints affect AI scaling?" and I'll search the brain for relevant material.
> 2. **Graph:** Open `graph-explorer.html` in your browser to see how concepts connect across domains.
> 3. **Cross-domain:** Ask something that spans domains, like "What's the relationship between chip supply chains and data centre location?" The brain pulls from multiple sources to synthesise an answer.
> 4. **Axioms in action:** Ask me to analyse a new AI company or product. Watch how the axioms (energy constraint, supply chain chokepoints, value migration) shape the analysis.
>
> **When you're ready to build your own brain:**
> You can keep the demo content and add to it, or clear everything and start fresh. To reset, just say "clear the brain and start over" — I'll wipe the demo data and you can begin with your own material.
>
> The full walkthrough is in `DEMO-WALKTHROUGH.md` in your working folder.
