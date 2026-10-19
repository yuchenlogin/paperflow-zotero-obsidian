import json
import tempfile
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch
import paperflow_summarize as pf


class PaperFlowTests(unittest.TestCase):
    def evidence(self):
        kinds = ['problem', 'method', 'method', 'method', 'training', 'result', 'ablation', 'related'] * 2
        entries = [{'kind': k, 'page': 1, 'claim': '机制说明', 'quote': f'Continuous source statement number {i} explains the model mechanism in detail.', 'numbers': []} for i, k in enumerate(kinds)]
        pages = [{'page': 1, 'text': '\n'.join(x['quote'] for x in entries)}]
        return {'evidence': entries}, pages

    def test_reject_forged_quotes_and_wrong_page(self):
        raw, pages = self.evidence()
        raw['evidence'][0]['page'] = 99
        raw['evidence'][1]['quote'] = 'Fabricated source statement with no basis in this paper whatsoever.'
        valid, rejected = pf.validate_evidence(raw, pages)
        self.assertEqual(len(valid), 14)
        self.assertEqual(len(rejected), 2)

    def test_reject_fabricated_numbers(self):
        raw, pages = self.evidence()
        raw['evidence'][0]['numbers'] = ['99.999']
        _, rejected = pf.validate_evidence(raw, pages)
        self.assertIn('数字', rejected[0]['reason'])

    def test_body_requires_real_citations(self):
        raw, pages = self.evidence()
        valid, _ = pf.validate_evidence(raw, pages)
        body = '\n'.join('## ' + h for h in pf.HEADINGS) + '\n' + '细致解释。' * 800 + '\n' + ' '.join('['+x['id']+']' for x in valid)
        pf.validate_body(body, valid)
        with self.assertRaises(ValueError):
            pf.validate_body(body + '\n不存在的结论 [E99]', valid)

    def test_existing_note_is_opened_without_model_call(self):
        with tempfile.TemporaryDirectory() as t:
            v = Path(t); w = v / '.paperflow/state/ABCD1234'; w.mkdir(parents=True)
            for n, value in [('meta', {'zotero_key':'ABCD1234'}), ('pages', []), ('info', {'source_type':'metadata_only'})]:
                (w/(n+'.json')).write_text(json.dumps(value))
            p = v/'Papers'/'Human title.md'; p.parent.mkdir(); p.write_text('---\nzotero_key: ABCD1234\n---\nHuman work')
            with patch.object(pf, 'chat', side_effect=AssertionError('must not call model')):
                result = pf.generate(w,v,v/'template.md',v/'Papers/ABCD1234.md')
            self.assertEqual(result,p.resolve())
            self.assertTrue(p.read_text().endswith('Human work'))

    def test_missing_fulltext_never_creates_fake_summary(self):
        with tempfile.TemporaryDirectory() as t:
            v=Path(t);w=v/'.paperflow/state/ABCD1234';w.mkdir(parents=True)
            for n,x in [('meta',{'zotero_key':'ABCD1234'}),('pages',[]),('info',{'source_type':'metadata_only'})]:
                (w/(n+'.json')).write_text(json.dumps(x))
            with self.assertRaisesRegex(ValueError,'完整 PDF'):
                pf.generate(w,v,v/'template.md',v/'Papers/new.md')
            self.assertFalse((v/'Papers/new.md').exists())

    def test_force_refuses_unmarked_human_notes(self):
        with tempfile.TemporaryDirectory() as t:
            v=Path(t);w=v/'state';w.mkdir()
            for n,x in [('meta',{'zotero_key':'ABCD1234'}),('pages',[]),('info',{'source_type':'fulltext'})]:
                (w/(n+'.json')).write_text(json.dumps(x))
            p=v/'Papers'/'Human.md';p.parent.mkdir();p.write_text('My human writing')
            with self.assertRaisesRegex(ValueError,'拒绝覆盖|同名文件'):
                pf.generate(w,v,v/'template.md',p,True)
            self.assertEqual(p.read_text(),'My human writing')

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            v=Path(t)
            with self.assertRaisesRegex(ValueError,'当前 vault'):
                pf.generate(v,v,v/'template.md',v.parent/'escape.md')

    def test_frontmatter_merge_preserves_user_properties(self):
        old='---\ntitle: "old"\ncreated: 2026-01-01\naliases:\n  - My Alias\ntags: [mine]\nreading_status: 已读\nproject: X\n---\nold'
        new='---\ntitle: "new"\ntags: [论文]\nreading_status: 未读\n---\nnew'
        result=pf.merge_user_frontmatter(new,old)
        props=pf.frontmatter_blocks(result)
        self.assertEqual(props['title'],'new')
        self.assertEqual(props['aliases'],['My Alias'])
        self.assertEqual(props['tags'],['mine'])
        self.assertEqual(props['reading_status'],'已读')
        self.assertEqual(str(props['created']),'2026-01-01')

    def test_wrong_numeric_citation_is_rejected_despite_value_on_unrelated_page(self):
        pages=[{'page':i,'text':('Unrelated 95.2' if i==9 else 'No measured number')} for i in range(1,11)]
        body='\n'.join('## '+h for h in pf.HEADINGS)+'\n'+'细致解释。'*800+'\n[P01] [P02] [P03] [P04]\nDataset X accuracy is 95.2% [P03]'
        with self.assertRaisesRegex(ValueError,'浮点数字'):
            pf.validate_body(body,[],pages)

    def test_computed_result_deltas_are_verified_arithmetically(self):
        self.assertTrue(pf.supported_calculation('4.99','53.83 48.84','53.83比48.84绝对提升4.99'))
        self.assertTrue(pf.supported_calculation('3.80','39.19 10.32','按表计算3.80倍'))
        self.assertFalse(pf.supported_calculation('99.99','53.83 48.84','绝对提升99.99'))
        self.assertFalse(pf.supported_calculation('4.99','53.83 48.84','作者实验报告4.99'))
        self.assertFalse(pf.supported_calculation('4.99','53.83 48.84','从53.83对比48.84，提升4.99倍'))
        self.assertFalse(pf.number_present('9.99%','Only 19.99%'))
        self.assertTrue(pf.supported_calculation('14.05','140,500 textual quadruples','14.05万条'))
        self.assertFalse(pf.supported_calculation('14.06','140,500 textual quadruples','14.06万条'))

    def test_preserve_concurrent_personal_edits_and_abort_ai_edits(self):
        for edit_ai in (False,True):
            with self.subTest(edit_ai=edit_ai),tempfile.TemporaryDirectory() as t:
                v=Path(t).resolve();w=v/'.paperflow/state/ABCD1234';w.mkdir(parents=True)
                note=v/'Papers/Test.md';note.parent.mkdir()
                old='---\nzotero_key: ABCD1234\ntitle: Test\n---\nOld AI\n'+pf.PERSONAL+'\nOld personal'
                note.write_text(old)
                raw,pages=self.evidence();evidence,_=pf.validate_evidence(raw,pages)
                meta={'zotero_key':'ABCD1234','title':'Test'}
                info={'source_type':'fulltext','pdf_sha256':'abc'}
                for name,obj in [('meta',meta),('pages',pages),('info',info)]:pf.save(w/(name+'.json'),obj)
                cache=hashlib.sha256(json.dumps({'source':'abc','model':'test','version':pf.VERSION},sort_keys=True).encode()).hexdigest()
                pf.save(w/'evidence.json',{'cache_key':cache,'evidence':evidence})
                template=v/'template.md';template.write_text('template')
                def rendering(*args):
                    note.write_text(old.replace('Old AI','Human edit') if edit_ai else old+'\nNew personal edit')
                    return '---\nzotero_key: ABCD1234\ntitle: Test\n---\nNew AI'
                with patch.object(pf,'config',return_value={'model':'test'}),patch.object(pf,'chat',return_value='Body'),patch.object(pf,'validate_body'),patch.object(pf,'render',side_effect=rendering):
                    if edit_ai:
                        with self.assertRaisesRegex(ValueError,'生成期间AI区域'):
                            pf.generate(w,v,template,note,True)
                        self.assertIn('Human edit',note.read_text())
                    else:
                        pf.generate(w,v,template,note,True)
                        self.assertIn('New personal edit',note.read_text())
                        self.assertIn('Old AI',note.read_text())
                        self.assertIn('New AI',next(w.glob('proposed-note-*.md')).read_text())

    def test_unicode_and_quoted_user_fields_preserved(self):
        old='---\n阅读进度: 已读\n"custom:key": X\ntitle: Old\n"日程": 周末\n---\nold'
        new='---\ntitle: New\n---\nnew'
        props=pf.frontmatter_blocks(pf.merge_user_frontmatter(new,old))
        self.assertEqual(props['阅读进度'],'已读')
        self.assertEqual(props['custom:key'],'X')
        self.assertEqual(props['日程'],'周末')

    def test_new_file_publication_cannot_clobber(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'note.md';p.write_text('human')
            with self.assertRaises(FileExistsError):pf.atomic_write(p,'generated',create_only=True)
            self.assertEqual(p.read_text(),'human')



if __name__ == '__main__':
    unittest.main()
