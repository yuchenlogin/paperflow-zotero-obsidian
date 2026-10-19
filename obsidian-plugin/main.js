const { Plugin, PluginSettingTab, Setting, Notice, SuggestModal, Modal, TFile } = require('obsidian');
const { execFile } = require('child_process');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const PERSONAL = '<!-- PAPERFLOW:PERSONAL -->';
const DEFAULT = { outputFolder: 'Papers', templatePath: '.obsidian/paperflow/templates/paper-summary.md', pythonPath: '', zoteroDataDir: '', openAfterCreate: true };

function parseKey(raw) {
  const text = String(raw || '').trim();
  if (/groups\//i.test(text)) return null;
  const m = text.match(/^(?:zotero:\/\/select\/library\/items\/)?([A-Z0-9]{8})$/i);
  return m ? m[1].toUpperCase() : null;
}
function physical(target) {
  try { return fs.realpathSync(target); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    try { if (fs.lstatSync(target).isSymbolicLink()) throw new Error('路径包含悬空符号链接'); }
    catch (statError) { if (statError.code !== 'ENOENT') throw statError; }
    return path.join(physical(path.dirname(target)), path.basename(target));
  }
}
function inside(base, relative) {
  const root = physical(path.resolve(base)), target = physical(path.resolve(base, relative));
  if (!target.startsWith(root + path.sep)) throw new Error('路径必须位于当前知识库内');
  return target;
}
function mergeProposal(current, proposed, expectedHash) {
  const at=current.indexOf(PERSONAL), next=proposed.indexOf(PERSONAL);
  if(at<0 || next<0) throw new Error('缺少个人记录保护标记，停止更新');
  const hash=crypto.createHash('sha256').update(current.slice(0,at),'utf8').digest('hex');
  if(hash!==expectedHash) throw new Error('生成期间正文或属性发生修改，已保留当前笔记；新稿位于 state 中');
  return proposed.slice(0,next)+current.slice(at);
}
class Picker extends SuggestModal {
  constructor(app, items, choose) { super(app); this.items = items; this.choose = choose; this.setPlaceholder('输入论文标题搜索 Zotero 文库…'); }
  getSuggestions(query) { return this.items.filter(i => i.title.toLowerCase().includes(query.toLowerCase())); }
  renderSuggestion(item, el) { el.createEl('div', { text: item.title }); el.createEl('small', { text: item.key }); }
  onChooseSuggestion(item) { this.choose(item.key); }
}
class KeyModal extends Modal {
  constructor(app, choose) { super(app); this.choose = choose; }
  onOpen() {
    this.titleEl.setText('从 Zotero 链接生成论文笔记');
    this.contentEl.createEl('p', { text: '粘贴 zotero://select/library/items/… 或八位条目 key。也可用“选择 Zotero 论文”按标题查找。' });
    const input = this.contentEl.createEl('input', { type: 'text' }); input.style.width = '100%';
    const submit = () => { const key = parseKey(input.value); if (!key) { new Notice('请选择个人文库论文父条目；链接或 key 无效'); return; } this.close(); this.choose(key); };
    input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    this.contentEl.createEl('button', { text: '生成或打开笔记' }).onclick = submit;
    input.focus();
  }
  onClose() { this.contentEl.empty(); }
}
module.exports = class PaperFlow extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULT, await this.loadData()); this.running = new Set();
    this.addRibbonIcon('book-open', 'PaperFlow：选择 Zotero 论文', () => this.pick());
    this.addCommand({ id: 'choose-zotero-paper', name: '选择 Zotero 论文（按标题，生成或打开）', callback: () => this.pick() });
    this.addCommand({ id: 'summarize-from-key', name: '从 Zotero 链接或 key 生成', callback: () => new KeyModal(this.app, key => this.generate(key)).open() });
    this.addCommand({ id: 'summarize-from-clipboard', name: '从剪贴板 Zotero 链接生成', callback: async () => { try { const key = parseKey(await navigator.clipboard.readText()); if (!key) throw new Error('剪贴板中无个人文库条目链接'); await this.generate(key); } catch (e) { new Notice(e.message); } } });
    this.addCommand({ id: 'summarize-current-note', name: '打开或生成当前论文笔记', callback: () => this.fromCurrent(false) });
    this.addCommand({ id: 'regenerate-current-note', name: '重新生成当前论文的 AI 区域（保留我的记录）', callback: () => this.fromCurrent(true) });
    this.addCommand({ id: 'open-guide', name: '打开使用说明', callback: () => this.app.workspace.openLinkText('System/PaperFlow Guide', '', false) });
    this.registerObsidianProtocolHandler('paperflow', params => {
      if (params.vault && params.vault !== this.app.vault.getName()) { new Notice('PaperFlow：目标知识库为 ' + params.vault + '，请在 Zotero → 工具 → PaperFlow 中设置正确名称'); return; }
      const key = parseKey(params.key); if (!key) { new Notice('PaperFlow：无效的 Zotero key'); return; }
      this.generate(key);
    });
    this.addSettingTab(new Settings(this.app, this));
  }
  base() { return physical(this.app.vault.adapter.getBasePath()); }
  script(name, args) {
    return new Promise((resolve, reject) => {
      const base = this.base();
      const python = this.settings.pythonPath || inside(base, '.paperflow/venv/bin/python');
      execFile(python, [inside(base, '.paperflow/' + name), ...args], { timeout: 1300000, maxBuffer: 8 * 1024 * 1024, env: { ...process.env, ...(this.settings.zoteroDataDir ? { PAPERFLOW_ZOTERO_DIR: this.settings.zoteroDataDir } : {}), PATH: '/opt/homebrew/bin:/usr/local/bin:' + (process.env.PATH || '') } }, (err, stdout, stderr) => {
        if (err) reject(new Error((stderr || err.message).slice(-1200))); else resolve(stdout);
      });
    });
  }
  async pick() {
    try { const items = JSON.parse(await this.script('paperflow_list.py', [])); new Picker(this.app, items, key => this.generate(key)).open(); }
    catch (e) { new Notice('PaperFlow：读取 Zotero 文库失败：' + e.message, 12000); }
  }
  async fromCurrent(force) {
    const file = this.app.workspace.getActiveFile(); if (!file) return;
    const text = await this.app.vault.read(file);
    const match = text.match(/^zotero[_-]key:\s*["']?([A-Z0-9]{8})["']?\s*$/m);
    if (!match) { new Notice('当前笔记没有 zotero_key，请按标题选择论文'); return; }
    if (!force) { await this.generate(match[1],false,file.path); return; }
    const modal = new Modal(this.app); modal.titleEl.setText('重新生成 AI 内容');
    modal.contentEl.createEl('p', { text: '会调用已配置模型、保存旧版，并保留“我的阅读记录”。AI 区域内的手动修改请先移至“我的阅读记录”。' });
    modal.contentEl.createEl('button', { text: '重新生成' }).onclick = () => { modal.close(); this.generate(match[1], true, file.path); };
    modal.contentEl.createEl('button', { text: '取消' }).onclick = () => modal.close(); modal.open();
  }
  async generate(key, force = false, targetPath = '') {
    if (!parseKey(key) || this.running.has(key)) { new Notice('该论文正在生成，或 key 无效'); return; }
    this.running.add(key);
    let progress;
    try {
      if (!force) {
        if(targetPath) {
          const current=this.app.vault.getAbstractFileByPath(targetPath);
          if(current instanceof TFile) { await this.app.workspace.getLeaf(false).openFile(current); return; }
        }
        const matches = this.app.vault.getMarkdownFiles().filter(f => {
          const fm=this.app.metadataCache.getFileCache(f)?.frontmatter;
          return (fm?.zotero_key || fm?.['zotero-key']) === key && f.path.startsWith(this.settings.outputFolder + '/');
        });
        if (matches.length > 1) throw new Error('同一条目存在多篇主笔记，请先合并');
        if (matches.length === 1) { await this.app.workspace.getLeaf(false).openFile(matches[0]); new Notice('已打开现有笔记'); return; }
      }
      progress = new Notice('PaperFlow：提取全文 → 核验原文证据 → 生成与检查（通常数分钟）', 0);
      const base = this.base();
      const args = [key, base, inside(base, this.settings.templatePath), inside(base, this.settings.outputFolder)];
      if (targetPath) args.push('--target', inside(base,targetPath));
      if (force) args.push('--force');
      const stdout = await this.script('paperflow_run.py', args);
      const match = stdout.match(/(?:FINAL_PATH|EXISTING_PATH)=(.+\.md)/);
      if (!match) throw new Error('后端未返回笔记路径');
      const relative = path.relative(base, match[1]).split(path.sep).join('/');
      if (relative.startsWith('../') || path.isAbsolute(relative)) throw new Error('后端返回了知识库外路径');
      const proposed=stdout.match(/PROPOSED_PATH=(.+\.md)/), expected=stdout.match(/EXPECTED_PREFIX_HASH=([a-f0-9]{64})/);
      if(proposed) {
        if(!expected) throw new Error('新稿缺少并发编辑检查信息');
        const proposalPath=inside(base,path.relative(base,proposed[1]));
        const next=fs.readFileSync(proposalPath,'utf8');
        const current=this.app.vault.getAbstractFileByPath(relative);
        if(!(current instanceof TFile)) throw new Error('原笔记已移动，保留新稿等待合并');
        await this.app.vault.process(current,data=>{
          const merged=mergeProposal(data,next,expected[1]);
          const history=inside(base,'.paperflow/history/'+key); fs.mkdirSync(history,{recursive:true});
          const name=new Date().toISOString().replace(/[:.]/g,'-')+'-'+crypto.randomBytes(4).toString('hex')+'.md';
          fs.writeFileSync(path.join(history,name),data,{encoding:'utf8',flag:'wx',mode:0o600});
          return merged;
        });
      }
      new Notice('PaperFlow：笔记已生成；阅读状态仍为“未读”，可从原文证据逐条核查', 10000);
      if (this.settings.openAfterCreate) await this.app.workspace.openLinkText(relative, '', false);
    } catch (e) { new Notice('PaperFlow：' + e.message, 16000); }
    finally { progress?.hide(); this.running.delete(key); }
  }
};
class Settings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    const el = this.containerEl; el.empty(); el.createEl('h2', { text: 'PaperFlow 2' });
    for (const [key, name] of [['outputFolder', '论文目录'], ['templatePath', '笔记模板'], ['pythonPath', 'Python 路径（留空使用独立环境）'], ['zoteroDataDir', 'Zotero 数据目录（留空使用 ~/Zotero）']]) {
      new Setting(el).setName(name).addText(t => t.setValue(this.plugin.settings[key]).onChange(async v => { this.plugin.settings[key] = v.trim(); await this.plugin.saveData(this.plugin.settings); }));
    }
    el.createEl('p', { text: '模型与 API key 保留在本地 .paperflow/config.json；Git 忽略不等于云同步排除。原文、书目及已有笔记的标题/summary 属性发送至所配置的模型服务；“我的阅读记录”正文不发送。' });
    new Setting(el).setName('使用说明').addButton(b => b.setButtonText('打开').onClick(() => this.app.workspace.openLinkText('System/PaperFlow Guide', '', false)));
  }
}
module.exports.parseKey = parseKey;
module.exports.inside = inside;
module.exports.mergeProposal = mergeProposal;
