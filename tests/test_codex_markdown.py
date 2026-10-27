import json
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import paperflow_codex as codex
import paperflow_markdown as md
import paperflow_summarize as pf


class CodexTransportTests(unittest.TestCase):
    def setup_cli(self, folder, fail=False):
        script=folder/'fake-codex'
        script.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
args=sys.argv[1:]
if args==['--version']:
    print('codex-cli 0.155.1')
    sys.exit(0)
prompt=sys.stdin.read()
Path(__file__).with_suffix('.request').write_text(json.dumps({'args':args,'prompt':prompt}))
if 'FAIL_TRANSPORT' in prompt:
    print('private-sentinel usage limit',file=sys.stderr)
    sys.exit(1)
Path(args[args.index('--output-last-message')+1]).write_text('FINAL_RESPONSE')
''')
        script.chmod(0o700)
        (folder/'config.toml').write_text('model="current-model"\nmodel_reasoning_effort="high"\nmodel_provider="custom"\n[model_providers.custom]\nname="OpenAI"\nrequires_openai_auth=true\nwire_api="responses"\n')
        return script

    def test_native_cli_receives_stdin_and_current_model_without_credentials(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);binary=self.setup_cli(folder)
            (folder/'auth.json').write_text('PRIVATE_AUTH_SENTINEL')
            with patch.dict(os.environ,{'CODEX_HOME':t,'PAPERFLOW_CODEX_MODEL':'','PAPERFLOW_CODEX_PATH':''}):
                cfg=codex.resolve({'transport':'codex-cli','codex_path':str(binary)})
                text=codex.chat(cfg,'paper text',True)
            self.assertEqual(text,'FINAL_RESPONSE')
            request=json.loads(binary.with_suffix('.request').read_text())
            self.assertIn('paper text',request['prompt'])
            self.assertIn('model="current-model"',request['args'])
            self.assertIn('--ephemeral',request['args'])
            self.assertNotIn('PRIVATE_AUTH_SENTINEL',json.dumps(request))
            answer=Path(request['args'][request['args'].index('--output-last-message')+1])
            self.assertFalse(answer.parent.exists())
            self.assertEqual((folder/'auth.json').read_text(),'PRIVATE_AUTH_SENTINEL')

    def test_transport_failure_stops_without_retry_or_private_diagnostics(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);binary=self.setup_cli(folder)
            with patch.dict(os.environ,{'CODEX_HOME':t,'PAPERFLOW_CODEX_MODEL':'','PAPERFLOW_CODEX_PATH':''}):
                cfg=codex.resolve({'codex_path':str(binary)})
                with self.assertRaisesRegex(RuntimeError,'用量') as failure:
                    codex.chat(cfg,'FAIL_TRANSPORT')
            self.assertNotIn('private-sentinel',str(failure.exception))

    def test_timeout_cancels_process_group_and_does_not_accept_partial_output(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);binary=self.setup_cli(folder)
            marker=folder/'child-finished'
            binary.write_text('''#!/usr/bin/env python3
import subprocess,sys,time
from pathlib import Path
if sys.argv[1:]==['--version']:
    print('codex-cli 0.155.1')
    sys.exit(0)
folder=Path(__file__).parent
child=subprocess.Popen([sys.executable,'-c',"import time; from pathlib import Path; time.sleep(1.5); Path("+repr(str(folder/'child-finished'))+").write_text('orphan')"])
(folder/'child-started').write_text(str(child.pid))
time.sleep(10)
''')
            with patch.dict(os.environ,{'CODEX_HOME':t,'PAPERFLOW_CODEX_MODEL':'','PAPERFLOW_CODEX_PATH':''}):
                cfg=codex.resolve({'codex_path':str(binary)});cfg['codex_timeout']=0.5
                with self.assertRaisesRegex(RuntimeError,'超时'):codex.chat(cfg,'fixture')
            self.assertTrue((folder/'child-started').exists())
            time.sleep(1.6)
            self.assertFalse(marker.exists())

    def test_custom_provider_with_credentials_or_url_is_not_copied_to_argv(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);self.setup_cli(folder)
            with (folder/'config.toml').open('a') as stream:stream.write('base_url="https://other.invalid"\n')
            with patch.dict(os.environ,{'CODEX_HOME':t}):
                with self.assertRaisesRegex(ValueError,'额外配置'):codex.resolve({})

    def test_codex_config_requires_no_api_key_and_api_default_is_compatible(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);binary=self.setup_cli(folder)
            state=folder/'.paperflow';state.mkdir()
            config=state/'config.json';config.write_text(json.dumps({'transport':'codex-cli','codex_path':str(binary)}))
            with patch.dict(os.environ,{'CODEX_HOME':t,'PAPERFLOW_TRANSPORT':'','PAPERFLOW_CONFIG':'','PAPERFLOW_CODEX_MODEL':'','PAPERFLOW_CODEX_PATH':''}):
                # config() accepts PAPERFLOW_CONFIG only when nonempty.
                os.environ.pop('PAPERFLOW_CONFIG',None)
                cfg=pf.config(folder)
                self.assertEqual(cfg['model'],'current-model')
                self.assertNotIn('api_key',cfg)
                config.write_text(json.dumps({'base_url':'https://example.invalid/v1','api_key':'test','model':'api-model'}))
                self.assertEqual(pf.config(folder)['transport'],'openai-compatible')


class ObsidianFormatTests(unittest.TestCase):
    def test_ranges_and_bold_numbering_normalize_without_touching_fenced_examples(self):
        text='```text\n[P01–P03]\n```\n[P01–P03]\n**1．问题**'
        result=md.normalize(text)
        self.assertIn('```text\n[P01–P03]\n```',result)
        self.assertTrue(result.endswith('[P01][P02][P03]\n1. **问题**'))
        self.assertEqual(md.normalize('Literal `[P01–P03]`'), 'Literal `[P01–P03]`')

    def test_html_and_broken_fences_are_rejected_but_literal_examples_are_allowed(self):
        for text in ('<details>\n<summary>x</summary>\n**body**\n</details>', '```mermaid\nflowchart LR'):
            with self.assertRaisesRegex(ValueError,'Obsidian'):md.validate(text)
        md.validate('Use `<details>` as a literal token.\n\n```html\n<details>\n```\n\n$x<y$\n<https://example.org>')
        md.validate('$$\nx<y>z\n$$', model_prose=True)
        md.validate('Use `<!--` as a literal token.\n\n```html\n<!--\n```')
        with self.assertRaisesRegex(ValueError,'块公式'):md.validate('$$\nx<y>z')

    def test_table_pipes_and_columns_are_checked(self):
        md.validate('| A | B |\n|---|---|\n| $\\lvert x\\rvert$ | a\\|b |')
        md.validate('> A | B\n> --- | ---\n> a | b')
        for text in ('| A | B |\n|---|---|\n| $|x|$ | b |','| A | B |\n|---|---|\n| a |',
                     'A | B\n--- | ---\na | b | c', '> | A | B |\n> |---|---|\n> | a | b | c |'):
            with self.assertRaisesRegex(ValueError,'表格列数'):md.validate(text)

    def test_appendix_is_native_foldable_markdown_with_valid_block_target(self):
        e={'id':'E01','page':1,'locator':'Sec. 1 [CLS]','quote':'Literal <points> and **not bold** source [12].'}
        with tempfile.TemporaryDirectory() as t:
            v=Path(t)
            text=pf.render({'zotero_key':'ABCD1234','title':'Test','zotero_attachment_key':'EFGH5678'},[e],
                           'Overview [E01]\n\n## 技术方法\n\nMechanism',{},
                           {'model':'test','transport':'codex-cli'},v,v/'Papers/Test.md')
        md.validate(text)
        self.assertNotIn('<details>',text)
        self.assertIn('> [!quote]- E01 · Sec. 1',text)
        self.assertIn('[E01](#^E01)',text)
        self.assertIn('\n\n^E01\n\n',text)
        self.assertIn('> Literal &lt;points&gt; and \\*\\*not bold\\*\\* source \\[12\\].',text)
        md.validate(md.folded_quote({**e,'quote':'Original labels: [P01-P03].'},'https://example.org'))
        md.validate(md.folded_quote({**e,'quote':'Original labels: [E01, E02].'},'https://example.org'))
        with self.assertRaisesRegex(ValueError,'来源编号'):md.validate('Unescaped [P01-P03]')
        with self.assertRaisesRegex(ValueError,'来源编号'):md.validate(r'Even backslashes \\[P01-P03]')

    def test_answers_must_be_nonempty_and_stay_inside_the_callout(self):
        section='\n\n'.join(f'{i}. **Question**\n\n> [!note]- 参考答案\n> Answer.\n>\n> More.' for i in range(1,5))
        md.validate_answers(section)
        for broken in (section.replace('> Answer.', 'Answer.',1),
                       section.replace('>\n> More.', '\n> More.',1),
                       section.replace('> Answer.\n>\n> More.','',1)):
            with self.assertRaisesRegex(ValueError,'callout'):md.validate_answers(broken)

    def test_render_escapes_literal_metadata_and_accepts_relative_image_destinations(self):
        meta={'zotero_key':'ABCD1234','title':'<i>Model</i> with <MASK>', 'display_title':'A <MASK> model',
              'venue':'Journal <Series>', 'url':'https://example.org'}
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t)
            with patch.object(pf,'figures',return_value=['![Figure](<Papers/ABCD1234/page-1-fixture.png>)']):
                text=pf.render(meta,[],'## 技术方法\n\nValid prose.',{}, {'model':'test'},vault,vault/'Assets/Test.md')
        md.validate(text)
        self.assertEqual(pf.frontmatter_blocks(text)['title'],meta['title'])
        self.assertIn('# A &lt;MASK&gt; model',text)
        self.assertIn('**&lt;i&gt;Model&lt;/i&gt; with &lt;MASK&gt;**',text)
        self.assertIn('![Figure](<Papers/ABCD1234/page-1-fixture.png>)',text)
        with self.assertRaisesRegex(ValueError,'HTML'):md.validate(text+'\n<details>bad</details>')

    def test_regeneration_refreshes_transport_provenance(self):
        old='---\ngenerator_transport: openai-compatible\nmy_property: retained\n---\nold'
        new='---\ngenerator_transport: codex-cli\n---\nnew'
        props=pf.frontmatter_blocks(pf.merge_user_frontmatter(new,old))
        self.assertEqual(props['generator_transport'],'codex-cli')
        self.assertEqual(props['my_property'],'retained')

    def test_unclosed_first_response_gets_one_correction_without_transport_retry(self):
        with tempfile.TemporaryDirectory() as t:
            vault=Path(t);work=vault/'state';work.mkdir()
            cfg={'model':'test','transport':'codex-cli'}
            info={'source_type':'fulltext','pdf_sha256':'fixture'}
            for name,value in [('meta',{'zotero_key':'ABCD1234','title':'Fixture'}),('pages',[]),('info',info)]:
                pf.save(work/(name+'.json'),value)
            cache=hashlib.sha256(json.dumps({'source':'fixture','model':'test','transport':'codex-cli','version':pf.VERSION},sort_keys=True).encode()).hexdigest()
            pf.save(work/'evidence.json',{'cache_key':cache,'evidence':[]})
            template=vault/'template.md';template.write_text('template')
            with patch.object(pf,'config',return_value=cfg), patch.object(pf,'validate_evidence',return_value=([],[])), \
                 patch.object(pf,'validate_body'), patch.object(pf,'chat',side_effect=['```mermaid\nflowchart LR','Corrected body']) as chat:
                out=pf.generate(work,vault,template,vault/'Papers/Fixture.md')
            self.assertTrue(out.exists())
            self.assertEqual(chat.call_count,2)
            self.assertIn('代码围栏未闭合',chat.call_args[0][1])
            self.assertEqual((work/'body-raw-1.md').read_text(),'```mermaid\nflowchart LR')

    def test_prompts_prohibit_defensive_filler_and_request_native_callouts(self):
        text=pf.synthesis_prompt({'title':'Test'},[],'')
        for requirement in ('禁止防御性写作','禁止废话','禁止原生 HTML','> [!note]- 参考答案','各行列数一致'):
            self.assertIn(requirement,text)

    def test_full_note_requires_foldable_answers_and_rejects_outer_code_wrapper(self):
        pages=[{'page':i,'text':'Source facts'} for i in range(1,5)]
        sections=[]
        for heading in pf.HEADINGS:
            content='机制与输入输出的具体说明。'*(20 if heading=='技术方法' else 3)
            if heading=='技术方法':content+='\n\n```mermaid\nflowchart LR\n A["Input"] --> B["Output"]\n```'
            if heading=='实验设置与结果':content+='\n\n| Model | Metric |\n|---|---|\n| A | observed |'
            if heading=='自测问题':content+='\n\n'+'\n\n'.join(f'{i}. **问题**\n\n> [!note]- 参考答案\n> 具体解释。[P0{i}]' for i in range(1,5))
            sections.append('## '+heading+'\n\n'+content)
        body='Overview [P01][P02][P03][P04]\n\n'+'\n\n'.join(sections)
        self.assertLess(len(body),3500)  # No padding required to meet a word quota.
        pf.validate_body(body,[],pages)
        pf.validate_body(body.replace('| Model | Metric |\n|---|---|\n| A | observed |',
                                      'Model | Metric\n:--- | ---:\nA | observed'),[],pages)
        with self.assertRaisesRegex(ValueError,'callout'):pf.validate_body(body.replace('> [!note]- 参考答案','Answer'),[],pages)
        with self.assertRaisesRegex(ValueError,'整篇'):pf.validate_body('~~~markdown\n'+body+'\n~~~',[],pages)
        start=body.index('## 技术方法')
        end=body.index('## 实验设置与结果')
        partially_wrapped=body[:start]+'````markdown\n'+body[start:end]+'````\n\n'+body[end:]
        with self.assertRaisesRegex(ValueError,'缺少或重复章节'):pf.validate_body(partially_wrapped,[],pages)
        with self.assertRaisesRegex(ValueError,'缺少或重复章节'):
            pf.validate_body(body.replace('## 技术方法','$$\n## 技术方法\n$$',1),[],pages)
        with self.assertRaisesRegex(ValueError,'缺少或重复章节'):
            pf.validate_body(body.replace('## 技术方法','<!--\n## 技术方法\n-->',1),[],pages)
        hidden_diagram=body.replace('```mermaid\nflowchart LR\n A["Input"] --> B["Output"]\n```',
                                    '````markdown\n```mermaid\nflowchart LR\n A["Input"] --> B["Output"]\n```\n````')
        with self.assertRaisesRegex(ValueError,'流程图'):pf.validate_body(hidden_diagram,[],pages)
        hidden_diagram=body.replace('```mermaid\nflowchart LR\n A["Input"] --> B["Output"]\n```',
                                    '<!--\n```mermaid\nflowchart LR\n A["Input"] --- B["Output"]\n```\n-->')
        with self.assertRaisesRegex(ValueError,'流程图'):pf.validate_body(hidden_diagram,[],pages)


if __name__=='__main__':unittest.main()
