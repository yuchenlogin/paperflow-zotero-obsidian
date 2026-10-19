/* Local Zotero bridge. No network server, database writes, or API credentials. */
var menuID;
var toolsMenuID;
function install() {}
function uninstall() {}
async function startup({id}) {
  await Zotero.initializationPromise;
  menuID = Zotero.MenuManager.registerMenu({
    menuID: 'paperflow-open-note', pluginID: id, target: 'main/library/item',
    menus: [{menuType: 'menuitem',
      onShowing(event, context) {
        context.menuElem.label = 'PaperFlow · 生成或打开 Obsidian 精读笔记';
        context.setVisible(context.items?.length === 1 && context.items[0].isRegularItem() && context.items[0].libraryID === Zotero.Libraries.userLibraryID);
      },
      onCommand(event, context) {
        const item = context.items?.[0];
        if (!item?.isRegularItem() || item.libraryID !== Zotero.Libraries.userLibraryID) return;
        const vault = Zotero.Prefs.get('extensions.paperflow.vault', true) || 'Obsidian Vault';
        Zotero.launchURL('obsidian://paperflow?vault=' + encodeURIComponent(vault) + '&key=' + encodeURIComponent(item.key));
      }
    }]
  });
  toolsMenuID = Zotero.MenuManager.registerMenu({
    menuID: 'paperflow-settings', pluginID: id, target: 'main/menubar/tools',
    menus: [{menuType: 'menuitem',
      onShowing(event, context) { context.menuElem.label = 'PaperFlow · 设置 Obsidian 知识库名称…'; },
      onCommand() {
        const value = {value: Zotero.Prefs.get('extensions.paperflow.vault', true) || 'Obsidian Vault'};
        if (Services.prompt.prompt(Zotero.getMainWindow(), 'PaperFlow', 'Obsidian 知识库名称（与 Obsidian 中显示的名称一致）', value, null, {})) {
          const name = value.value.trim();
          if (name) Zotero.Prefs.set('extensions.paperflow.vault', name, true);
        }
      }
    }]
  });
}
function shutdown() { if (menuID) Zotero.MenuManager.unregisterMenu(menuID); if (toolsMenuID) Zotero.MenuManager.unregisterMenu(toolsMenuID); }
