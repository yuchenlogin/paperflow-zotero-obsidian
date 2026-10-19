---
name: paperflow
description: Search a local Zotero personal library by title and generate detailed Chinese research-paper notes in Obsidian using an installed PaperFlow backend. Use for Zotero-to-Obsidian reading workflows and regenerating existing PaperFlow notes.
---

# PaperFlow

Use the existing local backend rather than replacing its note format with a new summary. Requires PaperFlow's Obsidian plugin, Python environment, model configuration, Poppler and a local Zotero personal library to be installed. If absent, use the repository README installation instructions; this skill alone does not install the application.

Determine the target vault from the user's context. Use its `.paperflow/venv/bin/python` (or the plugin's configured Python) for the bundled `scripts/run.py`:

```sh
"<vault>/.paperflow/venv/bin/python" "<skill-dir>/scripts/run.py" --vault "<vault>" --query "title substring"
"<vault>/.paperflow/venv/bin/python" "<skill-dir>/scripts/run.py" --vault "<vault>" --key "ABCD1234"
```

An empty query lists titles. Search is a case-insensitive title substring, not semantic or PDF search. Select the intended parent paper from returned titles and eight-character keys; if ambiguous, ask the user or show candidates. Group links and attachment keys are unsupported. The key command generates a new note or returns an existing note's path without a model call; it does not open a GUI window.

Read the returned Markdown and inspect important method/result source pages before reporting quality. Background, module-level method explanations, result tables, and substantive relations to actually collected papers should stay central. Distinguish direct research lineage, same-task alternatives and transferable mechanisms; do not manufacture connections. Cite checks establish source occurrence and structure, not full semantic correctness or replication.

No extractable full PDF means no full-paper note. Report the missing source rather than improvising from metadata. The backend makes bounded retries; after a failure, diagnose the error and stop repeated model calls without a new reason. Full paper text and existing titles/summary attributes are sent to the configured model service; never print credentials or upload private state/history to GitHub.

To regenerate an existing note, use Obsidian's `PaperFlow: 重新生成当前论文的 AI 区域（保留我的记录）` command so Vault.process coordinates the merge with editor writes. Do not manually overwrite the note or remove `<!-- PAPERFLOW:PERSONAL -->`. Direct CLI `--force` only produces a proposal; it does not publish over an existing note. Preserve user changes and explain any unresolved conflict.
