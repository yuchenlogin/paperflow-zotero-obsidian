#!/usr/bin/env python3
import json
import os
from pathlib import Path
from paperflow_fetch import snapshot

con = snapshot(Path(os.environ.get('PAPERFLOW_ZOTERO_DIR', Path.home() / 'Zotero')).resolve())
try:
    rows = con.execute("SELECT i.key,v.value AS title FROM items i JOIN itemData d USING(itemID) JOIN fields f USING(fieldID) JOIN itemDataValues v USING(valueID) JOIN libraries l USING(libraryID) WHERE f.fieldName='title' AND l.type='user' AND i.itemID NOT IN (SELECT itemID FROM deletedItems) AND i.itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes WHERE typeName IN ('attachment','note','annotation')) ORDER BY i.dateModified DESC").fetchall()
    print(json.dumps([dict(r) for r in rows], ensure_ascii=False))
finally:
    con.close()
