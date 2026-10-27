#!/usr/bin/env python3
"""Search installed PaperFlow, or generate/open a paper by its Zotero key."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--query',help='case-insensitive title substring; empty string lists all titles')
    group.add_argument('--key',help='personal-library parent key or zotero://select/library/items/ link')
    args=parser.parse_args()
    vault=Path(args.vault).expanduser().resolve()
    settings_path=vault/'.obsidian/plugins/paperflow/data.json'
    settings=json.loads(settings_path.read_text()) if settings_path.exists() else {}
    python=settings.get('pythonPath') or str(vault/'.paperflow/venv/bin/python')
    env=dict(os.environ)
    if settings.get('zoteroDataDir'): env['PAPERFLOW_ZOTERO_DIR']=settings['zoteroDataDir']
    def run(name, arguments):
        return subprocess.check_output([python,str(vault/'.paperflow'/name),*map(str,arguments)],env=env,text=True,timeout=3100)
    if args.query is not None:
        items=json.loads(run('paperflow_list.py',[]))
        print(json.dumps([x for x in items if args.query.casefold() in x['title'].casefold()],ensure_ascii=False,indent=2))
        return
    match=re.fullmatch(r'(?:zotero://select/library/items/)?([A-Z0-9]{8})',args.key.strip(),re.I)
    if not match: parser.error('需要个人文库论文父条目的八位 key 或 select 链接')
    key=match[1].upper()
    arguments=[key,vault,settings.get('templatePath','.obsidian/paperflow/templates/paper-summary.md'),settings.get('outputFolder','Papers')]
    print(run('paperflow_run.py',arguments),end='')

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print('PaperFlow failed: '+str(exc),file=sys.stderr);sys.exit(1)
