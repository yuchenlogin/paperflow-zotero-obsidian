#!/usr/bin/env python3
"""One transaction per paper across Obsidian and the standalone skill."""
import argparse
import json
import re
import sys
from pathlib import Path
from paperflow_fetch import fetch, locked_work
from paperflow_summarize import existing_note, generate


def inside(vault, relative):
    target = (vault / relative).resolve()
    if not target.is_relative_to(vault) or target == vault:
        raise ValueError('路径必须位于当前知识库内')
    return target


def note_title(raw, key):
    title = re.sub(r'[\x00-\x1f/\\?%*:|"<>]', ' ', str(raw or key))
    return re.sub(r'\s+', ' ', title).strip().encode('utf-8')[:180].decode('utf-8', errors='ignore').strip() or key


def run(key, vault, template, library_root, force=False, target=None):
    if not re.fullmatch(r'[A-Z0-9]{8}', key):
        raise ValueError('需要八位个人文库论文父条目 key')
    vault = Path(vault).resolve()
    root = inside(vault, library_root)
    template = inside(vault, template)
    output = inside(vault, target) if target else None
    known = existing_note(vault, key, root)
    if known and not force:
        print('EXISTING_PATH=' + str(known), flush=True)
        return known
    work = inside(vault, '.paperflow/state/' + key)
    # Outer lock spans fetch, metadata consumption, and synthesis. Stage locks
    # remain separate so direct developer commands cannot mutate active stages.
    with locked_work(work, '.job.lock'):
        known = existing_note(vault, key, root)
        if known and not force:
            print('EXISTING_PATH=' + str(known), flush=True)
            return known
        fetch(key, work)
        meta = json.loads((work / 'meta.json').read_text(encoding='utf-8'))
        if output is None:
            title = note_title(meta.get('title'), key)
            output = root / (title + '.md')
            if output.exists() and output != known:
                output = root / (title + ' — ' + key + '.md')
        return generate(work, vault, template, output, force, root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('key')
    parser.add_argument('vault')
    parser.add_argument('template')
    parser.add_argument('library_root')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--target')
    args = parser.parse_args()
    try:
        run(args.key, args.vault, args.template, args.library_root, args.force, args.target)
    except Exception as exc:
        print('[PaperFlow] ' + str(exc), file=sys.stderr)
        sys.exit(1)
