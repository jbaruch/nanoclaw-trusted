# Wiki Awareness

A persistent personal wiki lives at `/workspace/trusted/wiki/` with raw sources at `/workspace/trusted/sources/`.

## When to use the wiki

**Ingesting:** When the user shares a URL, article, PDF, transcript, or any source material and says to remember, file, catalog, research, or "add to wiki" — invoke the `wiki` skill to process it.

**Querying:** When answering questions that could benefit from accumulated knowledge — check `wiki/index.md` first. The wiki may have synthesized information from multiple sources that's richer than any single search result.

**Filing good answers:** When you produce a substantial, reusable answer (a comparison, a synthesis, a deep analysis) — offer to file it as a wiki page so it compounds rather than disappearing into chat history.

## Wiki vs memory

- **Memory** (`/workspace/trusted/MEMORY.md`) = operational context. Preferences, feedback, project state. Short entries.
- **Wiki** (`/workspace/trusted/wiki/`) = domain knowledge. Facts, concepts, entities, syntheses from sources. Structured pages with cross-references.

When you learn something operational (a correction, a preference), put it in memory.
When you learn domain knowledge (a fact, a concept, a pattern), put it in the wiki.
When answering questions, check both.

## Don't duplicate

If information belongs in the wiki, don't also put it in memory (and vice versa). One source of truth per type of knowledge.
