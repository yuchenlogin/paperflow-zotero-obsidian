const assert = require('assert');
const Module = require('module');
const load = Module._load;
Module._load = (name, ...args) => name === 'obsidian' ? { Plugin: class{}, PluginSettingTab:class{}, SuggestModal:class{}, Modal:class{} } : load(name, ...args);
const { parseKey, inside, mergeProposal } = require('../obsidian-plugin/main');
const crypto=require('crypto');
assert.equal(parseKey('zotero://select/library/items/ABCD1234'), 'ABCD1234');
assert.equal(parseKey('abcd1234'), 'ABCD1234');
assert.equal(parseKey('zotero://select/groups/123/items/ABCD1234'), null);
assert.equal(parseKey('ABCD1234; rm -rf anything'), null);
assert.throws(() => inside('/vault', '../outside'));
assert.throws(() => inside('/vault', '/vault-other/file'));
assert.equal(inside('/vault', 'Papers/a.md'), '/vault/Papers/a.md');
const fs=require('fs'), os=require('os'), path=require('path');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'paperflow-path-'));
try {
  const vault=path.join(temporary,'vault'), outside=path.join(temporary,'outside');
  fs.mkdirSync(vault); fs.mkdirSync(outside);
  const shortcut=path.join(temporary,'shortcut');fs.symlinkSync(vault,shortcut,'dir');
  const PaperFlow=require('../obsidian-plugin/main'), plugin=new PaperFlow();
  plugin.app={vault:{adapter:{getBasePath:()=>shortcut}}};
  assert.equal(plugin.base(),fs.realpathSync(vault));
  assert.equal(path.relative(plugin.base(),inside(shortcut,'Papers/Test.md')),'Papers/Test.md');
  fs.symlinkSync(outside,path.join(vault,'state'),'dir');
  assert.throws(()=>inside(vault,'state/ABCD1234/meta.json'));
  assert.equal(fs.readdirSync(outside).length,0);
} finally { fs.rmSync(temporary,{recursive:true,force:true}); }
console.log('Plugin routing and path tests passed');
const marker='<!-- PAPERFLOW:PERSONAL -->', prefix='AI v1\n';
const expected=crypto.createHash('sha256').update(prefix).digest('hex');
assert.equal(mergeProposal(prefix+marker+'latest user edit','AI v2\n'+marker+'stale user text',expected),'AI v2\n'+marker+'latest user edit');
assert.throws(()=>mergeProposal('human edited AI\n'+marker+'user','new\n'+marker,expected));
console.log('Editor-coordinated merge preserves latest personal text and aborts AI conflicts');

async function testVenvInterpreterSymlink() {
  const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'paperflow-venv-'));
  try {
    const vault=path.join(temporary,'vault'), outside=path.join(temporary,'outside');
    const bin=path.join(vault,'.paperflow/venv/bin');
    fs.mkdirSync(bin,{recursive:true});fs.mkdirSync(outside);
    // An external executable stands in for Python and emits an empty paper list.
    const interpreter=path.join(outside,'python');
    fs.writeFileSync(interpreter,'#!/bin/sh\nprintf \'[]\\n\'\n',{mode:0o755});
    fs.symlinkSync(interpreter,path.join(bin,'python'));
    fs.writeFileSync(path.join(vault,'.paperflow/paperflow_list.py'),'# list fixture\n');
    assert.throws(()=>inside(vault,'.paperflow/venv/bin/python'));
    const PaperFlow=require('../obsidian-plugin/main'), plugin=new PaperFlow();
    plugin.app={vault:{adapter:{getBasePath:()=>vault}}};plugin.settings={pythonPath:''};
    assert.deepEqual(JSON.parse(await plugin.script('paperflow_list.py',[])),[]);
    // The exemption is only for the executable leaf, not backend scripts.
    fs.unlinkSync(path.join(vault,'.paperflow/paperflow_list.py'));
    fs.writeFileSync(path.join(outside,'backend.py'),'# outside\n');
    fs.symlinkSync(path.join(outside,'backend.py'),path.join(vault,'.paperflow/paperflow_list.py'));
    await assert.rejects(()=>plugin.script('paperflow_list.py',[]),/知识库内/);
    fs.unlinkSync(path.join(vault,'.paperflow/paperflow_list.py'));
    fs.writeFileSync(path.join(vault,'.paperflow/paperflow_list.py'),'# list fixture\n');
    fs.rmSync(bin,{recursive:true});
    fs.symlinkSync(outside,bin,'dir');
    await assert.rejects(()=>plugin.script('paperflow_list.py',[]),/知识库内/);
    // Check Python's environment selection, not only execution of a shell stub.
    const realVault=path.join(temporary,'python-vault'),venv=path.join(realVault,'.paperflow/venv');
    require('child_process').execFileSync(process.env.PAPERFLOW_TEST_PYTHON || 'python3',['-m','venv','--without-pip',venv]);
    fs.writeFileSync(path.join(realVault,'.paperflow/paperflow_list.py'),'import json,sys\nprint(json.dumps({"prefix":sys.prefix,"base_prefix":sys.base_prefix}))\n');
    plugin.app={vault:{adapter:{getBasePath:()=>realVault}}};
    const ordinary=JSON.parse(await plugin.script('paperflow_list.py',[]));
    assert.equal(fs.realpathSync(ordinary.prefix),fs.realpathSync(venv));
    assert.notEqual(ordinary.prefix,ordinary.base_prefix);
    const sharedBin=path.join(realVault,'.paperflow/shared-bin');
    fs.renameSync(path.join(venv,'bin'),sharedBin);fs.symlinkSync(sharedBin,path.join(venv,'bin'),'dir');
    const linkedDirectory=JSON.parse(await plugin.script('paperflow_list.py',[]));
    const direct=JSON.parse(require('child_process').execFileSync(path.join(venv,'bin/python'),[path.join(realVault,'.paperflow/paperflow_list.py')],{encoding:'utf8'}));
    assert.equal(linkedDirectory.prefix,direct.prefix);
  } finally { fs.rmSync(temporary,{recursive:true,force:true}); }
}
testVenvInterpreterSymlink().then(()=>console.log('Plugin list entrypoint accepts a normal external interpreter symlink; rejects external scripts/directories'))
  .catch(error=>{ console.error(error); process.exitCode=1; });
