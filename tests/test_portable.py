import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paperflow_summarize as pf
import paperflow_fetch as fetcher
import paperflow_run as pipeline
from paperflow_fetch import snapshot, locked_work

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from install import install
from build import release_files


def pdf_fixture(path):
    # Self-authored one-page PDF with a colored rectangle; no third-party content.
    stream=b'0 0 1 rg 10 10 80 80 re f\n'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    data=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(data)
    data+=b'xref\n0 5\n0000000000 65535 f \n'+b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets[1:])
    data+=f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(data)


class PortableTests(unittest.TestCase):
    def test_settings_changes_require_obsidian_closed(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);install(vault)
            with self.assertRaisesRegex(ValueError,'--obsidian-closed'):
                install(vault,zotero_dir=vault/'zotero')

    def test_pipeline_keeps_job_lock_across_fetch_and_synthesis(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t).resolve();work=vault/'.paperflow/state/ABCD1234'
            def assert_locked():
                with self.assertRaisesRegex(RuntimeError,'已有任务'):
                    with locked_work(work,'.job.lock'): pass
            def fetch(key,destination):
                assert_locked()
                (destination/'meta.json').write_text('{"title":"Test"}')
            def generate(*args): assert_locked();return args[3]
            with patch.object(pipeline,'fetch',side_effect=fetch),patch.object(pipeline,'generate',side_effect=generate):
                pipeline.run('ABCD1234',vault,'.obsidian/template.md','Papers')

    def test_pipeline_rejects_state_symlink_and_long_unicode_filename_is_usable(self):
        with tempfile.TemporaryDirectory() as t,tempfile.TemporaryDirectory() as outside:
            vault=Path(t).resolve();state=vault/'.paperflow/state';state.mkdir(parents=True)
            (state/'ABCD1234').symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'知识库内'):
                pipeline.run('ABCD1234',vault,'template.md','Papers')
            filename=pipeline.note_title('中文研究标题'*100,'ABCD1234')+' — ABCD1234.md'
            path=vault/filename;path.write_text('works')
            self.assertLess(len(filename.encode()),255)

    def test_fetch_rejects_symlinked_state_file_without_writing_target(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);outside=folder/'personal.md';outside.write_text('personal')
            work=folder/'state';work.mkdir();(work/'meta.json').symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'符号链接'):
                fetcher.fetch('ABCD1234',work,folder/'no-database')
            self.assertEqual(outside.read_text(),'personal')

    def test_fetch_selects_personal_item_even_when_group_has_same_key(self):
        import sqlite3
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.executescript('''
CREATE TABLE libraries(libraryID INTEGER,type TEXT);
CREATE TABLE items(itemID INTEGER,libraryID INTEGER,itemTypeID INTEGER,key TEXT);
CREATE TABLE itemTypes(itemTypeID INTEGER,typeName TEXT);
CREATE TABLE deletedItems(itemID INTEGER);
CREATE TABLE itemData(itemID INTEGER,fieldID INTEGER,valueID INTEGER);
CREATE TABLE fields(fieldID INTEGER,fieldName TEXT);
CREATE TABLE itemDataValues(valueID INTEGER,value TEXT);
CREATE TABLE itemCreators(itemID INTEGER,creatorID INTEGER,orderIndex INTEGER);
CREATE TABLE creators(creatorID INTEGER,firstName TEXT,lastName TEXT);
CREATE TABLE itemAttachments(itemID INTEGER,parentItemID INTEGER,path TEXT,linkMode INTEGER,contentType TEXT);
INSERT INTO libraries VALUES(1,'group'),(2,'user');
INSERT INTO itemTypes VALUES(1,'journalArticle');
INSERT INTO items VALUES(1,1,1,'ABCD1234'),(2,2,1,'ABCD1234');
''')
        with tempfile.TemporaryDirectory() as t,patch.object(fetcher,'snapshot',return_value=con):
            meta,_,_=fetcher.fetch('ABCD1234',Path(t)/'state')
            self.assertEqual(meta['zotero_key'],'ABCD1234')

    def test_snapshot_retries_disappearing_wal_copy(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);con=sqlite3.connect(folder/'zotero.sqlite')
            con.execute('PRAGMA journal_mode=WAL');con.execute('CREATE TABLE sample(value)');con.commit()
            original=shutil.copy2;failed=[]
            def unstable(source,target):
                if str(source).endswith('-wal') and not failed:
                    failed.append(True);raise FileNotFoundError('WAL checkpoint race')
                return original(source,target)
            with patch.object(fetcher.shutil,'copy2',side_effect=unstable):
                copied=snapshot(folder);copied.close()
            self.assertEqual(failed,[True]);con.close()

    def test_transport_failure_does_not_stack_retries(self):
        from types import SimpleNamespace
        with patch.object(pf.subprocess,'run',return_value=SimpleNamespace(returncode=28)) as request:
            with self.assertRaisesRegex(RuntimeError,'连接失败'):
                pf.chat({'base_url':'https://example.invalid/v1','model':'test','api_key':'test-only'},'test')
            self.assertEqual(request.call_count,1)
            self.assertLessEqual(request.call_args.kwargs['timeout'],250)

    def test_install_dry_run_never_writes(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t)
            self.assertTrue(install(vault,dry_run=True))
            self.assertEqual(list(vault.iterdir()),[])

    def test_upgrade_preserves_config_template_settings_and_backs_up_code(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);install(vault)
            cfg=vault/'.paperflow/config.json';cfg.write_text('{"api_key":"private-sentinel"}')
            template=vault/'.obsidian/paperflow/templates/paper-summary.md';template.write_text('My custom template')
            code=vault/'.paperflow/paperflow_fetch.py';code.write_text('Old code')
            settings=vault/'.obsidian/plugins/paperflow/data.json';settings.write_text('{"outputFolder":"Library","custom":42}')
            install(vault,upgrade=True,zotero_dir=vault/'zotero',obsidian_closed=True)
            self.assertEqual(cfg.read_text(),'{"api_key":"private-sentinel"}')
            self.assertEqual(template.read_text(),'My custom template')
            self.assertEqual(json.loads(settings.read_text())['custom'],42)
            backups=list((vault/'.paperflow/install-backups').rglob('paperflow_fetch.py'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(),'Old code')

    def test_install_symlink_escape_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            vault=Path(a);outside=Path(b);(vault/'.paperflow').symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'越出'): install(vault)
            self.assertEqual(list(outside.iterdir()),[])
            self.assertFalse((vault/'.obsidian').exists())

    def test_reinstall_different_code_requires_upgrade(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);install(vault)
            (vault/'.paperflow/paperflow_fetch.py').write_text('local change')
            with self.assertRaisesRegex(ValueError,'--upgrade'): install(vault)

    def test_source_archive_allowlist_excludes_runtime_and_credentials(self):
        relative={p.relative_to(ROOT).as_posix() for p in release_files()}
        self.assertTrue(all(p.is_file() for p in release_files()))
        self.assertNotIn('backend/config.json',relative)
        self.assertNotIn('.paperflow/config.json',relative)
        self.assertNotIn('tests/private-note.md',relative)
        self.assertIn('zotero-bridge/manifest.json',relative)

    def test_local_snapshot_reads_wal_without_changing_source(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);db=folder/'zotero.sqlite'
            con=sqlite3.connect(db);con.execute('PRAGMA journal_mode=WAL')
            con.execute('CREATE TABLE sample(value)');con.execute("INSERT INTO sample VALUES ('committed in WAL')");con.commit()
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (db,Path(str(db)+'-wal'))}
            copied=snapshot(folder)
            self.assertEqual(copied.execute('SELECT value FROM sample').fetchone()[0],'committed in WAL')
            copied.close()
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (db,Path(str(db)+'-wal'))})
            con.close()

    def test_library_context_never_includes_personal_body(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);root=vault/'Library';root.mkdir()
            (root/'Test.md').write_text('---\nzotero_key: ABCD1234\ntitle: Public title\nsummary: Public mechanism\nprivate_property: SECRET_ATTRIBUTE\n---\n'+pf.PERSONAL+'SECRET_PERSONAL_BODY')
            context=pf.library_context(vault,root)
            self.assertIn('[[Library/Test]]',context)
            self.assertIn('Public mechanism',context)
            self.assertNotIn('SECRET_',context)

    def test_skill_returns_existing_note_without_model_or_pdf(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);install(vault)
            settings=vault/'.obsidian/plugins/paperflow/data.json';settings.write_text(json.dumps({'pythonPath':sys.executable}))
            papers=vault/'Papers';papers.mkdir();note=papers/'Human title.md'
            note.write_text('---\nzotero_key: ABCD1234\n---\nHuman work')
            result=subprocess.run([sys.executable,'-S',str(ROOT/'skills/paperflow/scripts/run.py'),'--vault',str(vault),'--key','ABCD1234'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('EXISTING_PATH='+str(note.resolve()),result.stdout)
            self.assertFalse((vault/'.paperflow/state').exists())

    @unittest.skipUnless(shutil.which('pdftoppm'),'Poppler required')
    def test_crop_uses_real_pdf_and_cache_changes_with_coordinates(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);pdf=vault/'fixture.pdf';pdf_fixture(pdf)
            info={'pdf':str(pdf),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}
            meta={'zotero_key':'ABCD1234','zotero_attachment_key':'EFGH5678'}
            config=vault/'.paperflow/figure-regions.json';config.parent.mkdir()
            output=vault/'Papers/Test.md';output.parent.mkdir()
            for crop in ([0,0,0.5,0.5],[0,0,1,1]):
                config.write_text(json.dumps({'ABCD1234':[{'page':1,'crop':crop,'role':'method'}]}))
                blocks=pf.figures(meta,[],info,vault,output)
                self.assertIn('page=1',blocks[0])
            images=list((vault/'Assets/Papers/ABCD1234').glob('*.png'))
            self.assertEqual(len(images),2)
            sizes=[]
            for p in images:
                with Image.open(p) as image: sizes.append(image.size)
            self.assertEqual(sorted(sizes),[(1000,1000),(2000,2000)])

if __name__=='__main__': unittest.main()
