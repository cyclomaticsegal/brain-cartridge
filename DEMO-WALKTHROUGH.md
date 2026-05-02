# Demo Walkthrough — See Your Brain in Action

This guide walks you through the demo experience step by step. By the end, you'll have a working brain with real content, a visual knowledge graph, and analytical frameworks — and you'll understand how to build your own.

---

## What the demo builds

The demo populates your brain with six documents across three interconnected domains:

**AI & Frontier Lab Economics.** How scaling laws drive billion-dollar training runs. Why model quality is converging and competitive advantage is shifting to distribution. How AI agents are restructuring the application layer and creating new infrastructure businesses.

**Geopolitics of AI.** Why TSMC's chip fabrication monopoly is a geopolitical flashpoint. How US-China export controls are reshaping the semiconductor industry. Why sovereign AI is driving compute nationalism. How the EU, US, and China are taking divergent approaches to AI regulation.

**Energy & Compute Infrastructure.** Why energy is the binding constraint on AI scaling. How data centre power demand is straining electrical grids. Why nuclear power is experiencing a renaissance. How cooling technology and grid connection bottlenecks shape where AI infrastructure gets built.

These three domains form a natural triangle: AI labs need chips, chips need energy, and geopolitics determines who gets access to both. The cross-domain connections are the whole point — they're what makes a knowledge graph more useful than a filing cabinet.

---

## Running the demo

### Step 1: Set up your brain

If you haven't already, start a Cowork task with the brain cartridge as your working folder. Say "start my brain" to trigger the bootstrap. Give it a name when prompted. You can skip the axiom seeding — the demo will handle that.

### Step 2: Launch the demo

Say `/demo-brain` or "run the demo". Claude will check for the demo data, show you what's about to happen, and ask for confirmation.

### Step 3: Watch the ingestion

Claude copies the six demo documents into the inbox and runs the ingestion pipeline. Here's what happens behind the scenes:

1. **Source ID assignment.** Each document gets a unique ID (S01, S02, etc.) and is moved from `inbox/` to `sources/` with a clean filename.

2. **Chunking.** Each document is split into overlapping segments of roughly 512 tokens. This creates the searchable units — when you ask a question later, the brain finds the most relevant chunks, not whole documents.

3. **Embedding.** Each chunk gets a vector representation — a mathematical fingerprint that captures its meaning. This enables semantic search: finding content that's conceptually related to your query, even if it uses different words.

4. **Domain classification.** The engine analyses each document's content against a set of domain keyword descriptions and assigns it to the most relevant knowledge domain. This is automatic but can be overridden manually.

5. **Graph construction.** Concept nodes are extracted from the content and connected by typed edges. Domain nodes act as hubs. The result is a directed graph that captures how ideas relate across your knowledge base.

6. **Graph export.** The graph data is written to `GRAPH.json` and the visual explorer (`graph-explorer.html`) is updated with the new data and legend.

### Step 4: Explore what was built

After ingestion, you have several things to look at:

**Search the brain.** Ask Claude a question that spans the demo content. Good ones to try:

- "How do energy constraints affect AI scaling?"
- "What's the relationship between chip export controls and data centre location?"
- "Why are frontier labs converging on similar model quality?"
- "What's Jevons' paradox and why does it matter for AI?"

Claude will search the brain, pull relevant chunks from multiple sources, and synthesise an answer grounded in your specific material. Notice how it cites which sources informed the answer.

**Open the knowledge graph.** Open `graph-explorer.html` in your browser. You'll see domain nodes (large, gold), concept nodes (coloured by domain), and edges connecting them. Try:

- Clicking a node to see its connections and highlight its neighbourhood.
- Using the domain legend (bottom left) to filter by domain.
- Clicking "Cluster" to group nodes by domain.
- Using "Search" to find specific concepts.
- Clicking "Edge Labels" to see the relationship types.

The graph shows the cross-domain connections visually. You'll see concepts from the AI domain connected to concepts in the energy domain, connected to concepts in the geopolitics domain. That triangulation is what makes a knowledge graph more powerful than separate document collections.

**Read the axioms.** Open `AXIOMS.md` in a text editor. The demo seeds three frameworks:

- **Energy as Constraint** — a lens for evaluating anything involving AI infrastructure.
- **Supply Chain Chokepoints** — a lens for identifying strategic vulnerabilities.
- **Value Migration from Technology to Distribution** — a lens for evaluating competitive dynamics.

These aren't conclusions — they're analytical instructions. When Claude encounters a question where one of these frameworks applies, it uses the axiom to know what to look for, then searches the brain for the detailed material. The axiom is the signpost; the brain is the library.

### Step 5: See the axioms in action

Ask Claude to analyse something new using your frameworks. For example:

- "Analyse NVIDIA's competitive position using my frameworks."
- "What would my axioms say about a new country trying to build sovereign AI capability?"
- "Evaluate whether cloud providers or AI labs will capture more value over the next five years."

Watch how Claude applies the three axioms — energy constraint, supply chain chokepoints, value migration — as lenses, and grounds the analysis in your ingested material. This is the brain working as designed: your frameworks applied to your knowledge, producing analysis that's specifically yours.

---

## After the demo

You have three options:

**Keep and extend.** The demo content stays in your brain. Drop your own documents into `inbox/`, run an ingestion, and your material joins the demo content. The graph grows, new cross-domain connections emerge, and Claude proposes new axioms as patterns appear.

**Reset and start fresh.** Tell Claude "clear the brain and start over." This wipes all ingested content, graph nodes, and edges. Your brain name is preserved. You start with a clean slate and your own material.

**Selective cleanup.** If you want to keep some demo content but not all, you can manually remove specific sources. The brain engine handles this — ask Claude for help if needed.

---

## Building your own brain

The demo showed you the mechanics. Here's how to apply them to your own intellectual interests:

1. **Collect material.** Gather documents that represent how you think: articles you've saved, notes you've written, PDFs you keep returning to. They don't need to be polished — raw notes work fine. Drop them in `inbox/`.

2. **Ingest.** Say "process my inbox." The engine handles the rest.

3. **Let axioms emerge.** After ingesting 5-10 sources, Claude will start noticing patterns. It may propose axioms: "Your material keeps returning to [theme]. Want me to add this as a framework?" You approve, refine, or reject.

4. **Declare axioms directly.** If you already know your analytical lenses — "I think about everything through network effects and incentive design" — tell Claude. It'll write initial axiom entries that sharpen as you ingest material.

5. **Explore the graph.** After each ingestion, open the graph explorer. Watch how new material connects to what's already there. The cross-domain connections are where the most interesting insights live.

6. **Iterate.** A brain is a living system. Add material, refine axioms, explore connections. The more you put in, the more useful it becomes.
