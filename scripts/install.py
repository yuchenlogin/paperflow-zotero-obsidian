#!/usr/bin/env python3
"""Install maintained source files; preserve user configuration and templates."""
import argparse
import json
import os
import shutil
import tempfile
import fcntl
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inside(vault, relative):
    result = (vault / relative).resolve()
    if not result.is_relative_to(vault) or result == vault:
        raise ValueError(f'安装路径越出知识库：{relative}')
    return result


def _install(vault, upgrade=False, dry_run=False, zotero_dir=None, obsidian_closed=False):
    vault = Path(vault).expanduser().resolve()
    if not vault.is_dir():
        raise ValueError('请提供已经存在的 Obsidian 知识库目录')
    files = {f'.paperflow/{p.name}': p for p in (ROOT/'backend').glob('*.py')}
    files.update({f'.obsidian/plugins/paperflow/{n}': ROOT/'obsidian-plugin'/n for n in ('main.js','manifest.json')})
    files['System/PaperFlow Guide.md'] = ROOT/'docs/usage.md'
    template = '.obsidian/paperflow/templates/paper-summary.md'
    files[template] = ROOT/'templates/paper-summary.md'
    files['.paperflow/config.json'] = ROOT/'config.example.json'
    files['.paperflow/requirements.txt'] = ROOT/'requirements.txt'
    protected = {template, '.paperflow/config.json'}
    # Validate every destination before any mutation, including symlink parents.
    targets = {rel: inside(vault, rel) for rel in files}
    data = inside(vault, '.obsidian/plugins/paperflow/data.json')
    state_dir = inside(vault, '.paperflow')
    backup = inside(vault, '.paperflow/install-backups/'+datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    changes = []
    for rel, source in files.items():
        target = targets[rel]
        if target.exists():
            if rel in protected or target.read_bytes() == source.read_bytes():
                continue
            if not upgrade:
                raise ValueError(f'{rel} 已存在且内容不同；使用 --upgrade 备份后更新代码')
        changes.append((rel, source))
    settings = json.loads(data.read_text()) if data.exists() else {}
    new_settings = dict(settings)
    if zotero_dir is not None:
        new_settings['zoteroDataDir'] = str(Path(zotero_dir).expanduser().resolve())
    if new_settings != settings and not dry_run and not obsidian_closed:
        raise ValueError('修改插件设置前请退出 Obsidian，再加 --obsidian-closed；也可在 Obsidian 设置中修改 Zotero 数据目录')
    if dry_run:
        return [rel for rel, _ in changes] + (['.obsidian/plugins/paperflow/data.json'] if new_settings != settings else [])
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for rel, source in changes:
        target = targets[rel]
        if target.exists():
            saved = backup/rel
            saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(target, saved)
            saved.chmod(0o600)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.paperflow-install-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(source.read_bytes())
            os.replace(temp,target)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    if new_settings != settings:
        # Only the explicitly requested setting changes; never overwrite API config.
        fd, temp = tempfile.mkstemp(prefix='.paperflow-settings-',dir=data.parent)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(new_settings,stream,ensure_ascii=False,indent=2)
            os.replace(temp,data)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return [rel for rel, _ in changes]


def install(vault, upgrade=False, dry_run=False, zotero_dir=None, obsidian_closed=False):
    vault=Path(vault).expanduser().resolve()
    if dry_run:
        return _install(vault,upgrade,dry_run,zotero_dir,obsidian_closed)
    if not vault.is_dir():
        raise ValueError('请提供已经存在的 Obsidian 知识库目录')
    lock=inside(vault,'.paperflow/install.lock')
    if lock.is_symlink():
        raise ValueError('拒绝符号链接安装锁')
    lock.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with lock.open('a') as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('已有安装任务运行，请稍后重试') from None
        try: return _install(vault,upgrade,dry_run,zotero_dir,obsidian_closed)
        finally: fcntl.flock(handle,fcntl.LOCK_UN)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault',required=True)
    parser.add_argument('--upgrade',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--zotero-dir')
    parser.add_argument('--obsidian-closed',action='store_true',help='确认已退出 Obsidian；写入插件设置时必需')
    args = parser.parse_args()
    try:
        paths=install(args.vault,args.upgrade,args.dry_run,args.zotero_dir,args.obsidian_closed)
        print(('Would install: ' if args.dry_run else 'Installed: ')+', '.join(paths))
        if not args.dry_run: print('Next: create .paperflow/venv, install requirements, configure model, enable PaperFlow in Obsidian. See README.md.')
    except (ValueError,OSError) as exc:
        parser.exit(1,str(exc)+'\n')
