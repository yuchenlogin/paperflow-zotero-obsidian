#!/usr/bin/env python3
"""Read-only checks; never call the model or display credentials."""
import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

def check(vault):
    vault=Path(vault).expanduser().resolve()
    results=[]
    def record(name, ok): results.append({'check':name,'ok':bool(ok)})
    record('Python >= 3.10 on macOS/Linux',sys.version_info >= (3,10) and sys.platform != 'win32')
    for module in ('yaml','PIL'):
        record('dependency '+module,importlib.util.find_spec(module) is not None)
    for executable in ('pdftotext','pdftoppm','curl'):
        record('executable '+executable,shutil.which(executable))
    for name in ('paperflow_fetch.py','paperflow_summarize.py','paperflow_list.py','paperflow_run.py','paperflow_codex.py','paperflow_markdown.py'):
        record('backend '+name,(vault/'.paperflow'/name).is_file())
    plugin=vault/'.obsidian/plugins/paperflow'
    record('Obsidian plugin',(plugin/'main.js').is_file() and (plugin/'manifest.json').is_file())
    settings=json.loads((plugin/'data.json').read_text()) if (plugin/'data.json').exists() else {}
    record('template',(vault/settings.get('templatePath','.obsidian/paperflow/templates/paper-summary.md')).is_file())
    db=Path(settings.get('zoteroDataDir') or os.environ.get('PAPERFLOW_ZOTERO_DIR') or Path.home()/'Zotero')/'zotero.sqlite'
    record('Zotero database exists',db.is_file())
    cfg_path=Path(os.environ.get('PAPERFLOW_CONFIG') or vault/'.paperflow/config.json')
    cfg=json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    transport=os.environ.get('PAPERFLOW_TRANSPORT') or cfg.get('transport','openai-compatible')
    record('supported transport',transport in ('codex-cli','openai-compatible'))
    if transport=='codex-cli':
        sys.path.insert(0,str(vault/'.paperflow'))
        try:
            from paperflow_codex import resolve
            resolved=resolve(cfg)
            record('Codex CLI and current model configured',bool(resolved['model']))
        except (ValueError,OSError,ImportError):
            record('Codex CLI and current model configured',False)
    else:
        for key in ('base_url','model','api_key'):
            value=os.environ.get('PAPERFLOW_'+key.upper()) or cfg.get(key,'')
            record('configured '+key,value and 'REPLACE_WITH_' not in value and 'api.example.com' not in value)
    enabled=vault/'.obsidian/community-plugins.json'
    record('PaperFlow enabled in Obsidian',enabled.exists() and 'paperflow' in json.loads(enabled.read_text()))
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return all(r['ok'] for r in results)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault',required=True)
    args=parser.parse_args()
    try: sys.exit(0 if check(args.vault) else 1)
    except (ValueError,OSError): parser.exit(1,'配置不可读或 JSON 无效；未显示配置内容。\n')
