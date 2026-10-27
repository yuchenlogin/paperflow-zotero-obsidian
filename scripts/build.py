#!/usr/bin/env python3
"""Build source + optional experimental bridge from an explicit allowlist."""
import json
import hashlib
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def release_files():
    paths = '''README.md LICENSE CHANGELOG.md .gitignore requirements.txt config.example.json config.codex.example.json
backend/paperflow_fetch.py backend/paperflow_list.py backend/paperflow_summarize.py backend/paperflow_run.py backend/paperflow_codex.py backend/paperflow_markdown.py
obsidian-plugin/main.js obsidian-plugin/manifest.json templates/paper-summary.md
scripts/install.py scripts/doctor.py scripts/build.py
skills/paperflow/SKILL.md skills/paperflow/scripts/run.py
tests/test_paperflow.py tests/test_portable.py tests/test_codex_markdown.py tests/test_codex_native.py tests/test_plugin.js
docs/usage.md docs/architecture.md
.github/workflows/test.yml zotero-bridge/manifest.json zotero-bridge/bootstrap.js'''.split()
    return [ROOT/p for p in sorted(paths)]

if __name__=='__main__':
    version=json.loads((ROOT/'obsidian-plugin/manifest.json').read_text())['version']
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    bundle=dist/f'paperflow-{version}-source.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in release_files(): archive.write(p,Path('paperflow')/p.relative_to(ROOT))
    # Experimental bridge is deliberately separate from the default source bundle.
    bridge=dist/f'paperflow-bridge-{version}-experimental.xpi'
    with zipfile.ZipFile(bridge,'w',zipfile.ZIP_DEFLATED) as archive:
        for n in ('manifest.json','bootstrap.js'): archive.write(ROOT/'zotero-bridge'/n,n)
    skill=dist/f'paperflow-skill-{version}.zip'
    with zipfile.ZipFile(skill,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in release_files():
            if p.is_relative_to(ROOT/'skills/paperflow'):
                archive.write(p,Path('paperflow')/p.relative_to(ROOT/'skills/paperflow'))
    checksum=dist/'SHA256SUMS.txt'
    checksum.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (bundle,skill,bridge)))
    for p in (bundle,skill,bridge,checksum): print(p)
