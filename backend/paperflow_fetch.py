#!/usr/bin/env python3
"""PaperFlow 2: consistent read-only Zotero snapshot and page-addressed PDF text."""
import hashlib
import fcntl
import json
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def locked_work(directory, name='.run.lock'):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    lock = directory/name
    if lock.is_symlink():
        raise ValueError('拒绝符号链接锁文件')
    with open(lock,'a') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('该论文已有任务运行，请等待完成后再打开') from None
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)


def dump(path, obj):
    if path.is_symlink():
        raise ValueError('拒绝写入符号链接状态文件')
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot(data_dir):
    # Zotero can use an exclusive lock. Clone the main DB and WAL across a
    # verified quiet interval, then let SQLite replay WAL in that private copy.
    db = data_dir / "zotero.sqlite"
    paths = [db, Path(str(db) + "-wal")]
    def stamps():
        result=[]
        for p in paths:
            try:
                stat=p.stat()
                result.append((stat.st_ino,stat.st_size,stat.st_mtime_ns))
            except FileNotFoundError:
                result.append(None)
        return result
    with tempfile.TemporaryDirectory(prefix="paperflow-snapshot-") as temp:
        for attempt in range(5):
            before = stamps()
            try:
                for p in paths:
                    target = Path(temp) / p.name
                    if p.exists():
                        shutil.copy2(p, target)
                    elif target.exists():
                        target.unlink()
            except FileNotFoundError:
                continue
            if before != stamps():
                continue
            copy = sqlite3.connect((Path(temp) / db.name).as_uri() + "?mode=ro", uri=True)
            dst = sqlite3.connect(":memory:")
            try:
                copy.backup(dst)
            finally:
                copy.close()
            dst.row_factory = sqlite3.Row
            return dst
    raise RuntimeError("Zotero 数据库持续变化，无法取得一致快照；请稍后重试")


def _fetch(key, output, data_dir=None):
    if not re.fullmatch(r"[A-Z0-9]{8}", key):
        raise ValueError("Zotero key 必须是八位大写字母/数字")
    data_dir = Path(data_dir or os.environ.get("PAPERFLOW_ZOTERO_DIR", Path.home() / "Zotero")).resolve()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ('meta.json','pages.json','info.json','text.txt'):
        if (output/name).is_symlink():
            raise ValueError('拒绝写入符号链接状态文件')
    con = snapshot(data_dir)
    try:
        row = con.execute("SELECT i.itemID,i.libraryID,t.typeName FROM items i JOIN itemTypes t USING(itemTypeID) JOIN libraries l USING(libraryID) WHERE i.key=? AND l.type='user' AND i.itemID NOT IN (SELECT itemID FROM deletedItems)", (key,)).fetchone()
        if not row:
            raise ValueError(f"未找到 Zotero 条目 {key}")
        if row["typeName"] in ("attachment", "note", "annotation"):
            raise ValueError("请选择论文父条目，而非 PDF 附件或子笔记")
        iid = row["itemID"]
        # This workflow currently supports the personal library only.
        library = con.execute("SELECT type FROM libraries WHERE libraryID=?", (row["libraryID"],)).fetchone()
        if library and library["type"] != "user":
            raise ValueError("当前只支持个人文库；群组文库需单独配置链接与身份")
        fields = dict(con.execute("SELECT f.fieldName,v.value FROM itemData d JOIN fields f USING(fieldID) JOIN itemDataValues v USING(valueID) WHERE d.itemID=?", (iid,)))
        creators = con.execute("SELECT c.firstName,c.lastName FROM itemCreators ic JOIN creators c USING(creatorID) WHERE ic.itemID=? ORDER BY ic.orderIndex", (iid,)).fetchall()
        year = re.search(r"\d{4}", fields.get("date", ""))
        meta = {"zotero_key": key, "title": fields.get("title", key), "authors": [" ".join(filter(None, [c[0], c[1]])) for c in creators], "year": year[0] if year else "", "venue": fields.get("proceedingsTitle") or fields.get("publicationTitle", ""), "doi": fields.get("DOI", ""), "url": fields.get("url", ""), "abstract": fields.get("abstractNote", ""), "citation_key": key, "item_type": row["typeName"]}
        attachments = con.execute("SELECT i.key,a.path,a.linkMode FROM itemAttachments a JOIN items i USING(itemID) WHERE a.parentItemID=? AND a.contentType='application/pdf' AND a.itemID NOT IN (SELECT itemID FROM deletedItems) ORDER BY a.itemID", (iid,)).fetchall()
    finally:
        con.close()
    pdf, attachment_key = None, ""
    for att in attachments:
        raw = att["path"] or ""
        if raw.startswith("storage:"):
            candidate = data_dir / "storage" / att["key"] / raw[len("storage:"):]
        elif Path(raw).is_absolute():
            candidate = Path(raw)
        else:
            continue  # Do not guess a linked attachment base directory.
        if candidate.is_file():
            pdf, attachment_key = candidate.resolve(), att["key"]
            break
    meta["zotero_attachment_key"] = attachment_key
    text = ""
    original_pdf=str(pdf) if pdf else ''
    pdf_hash=''
    if pdf:
        before=pdf.stat()
        content=pdf.read_bytes()
        after=pdf.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
            raise RuntimeError('PDF 在读取时发生变化，请重试')
        pdf_hash=hashlib.sha256(content).hexdigest()
        cached=output/('source-'+pdf_hash+'.pdf')
        if cached.is_symlink():
            raise ValueError('拒绝符号链接 PDF 缓存')
        if not cached.exists():cached.write_bytes(content)
        elif hashlib.sha256(cached.read_bytes()).hexdigest()!=pdf_hash:
            raise RuntimeError('本地 PDF 快照校验失败，停止使用缓存')
        pdf=cached.resolve()
        # Reading-order extraction avoids interleaving two-column paragraphs.
        proc = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=True, timeout=90)
        text = proc.stdout.decode("utf-8", errors="replace")
    parts = text.split("\f")
    if parts and not parts[-1].strip():
        parts.pop()
    pages = [{"page": i + 1, "text": t} for i, t in enumerate(parts)] if text.strip() else []
    info = {"pdf": str(pdf) if pdf else "", "original_pdf":original_pdf,"chars": len(text), "page_count": len(pages), "pdf_sha256": pdf_hash, "source_type": "fulltext" if len(text.strip()) > 1500 else "metadata_only", "fetch_method": "consistent-db-and-wal-copy-then-sqlite-backup"}
    dump(output / "meta.json", meta)
    dump(output / "pages.json", pages)
    dump(output / "info.json", info)
    # Keep private annotations local; generation does not read or transmit them.
    (output / "text.txt").write_text(text, encoding="utf-8")
    print(f"[fetch] {key}: {meta['title']} — {len(pages)} pages; {info['source_type']}", flush=True)
    return meta, pages, info


def fetch(key,output,data_dir=None):
    with locked_work(output):
        return _fetch(key,output,data_dir)


if __name__ == "__main__":
    try:
        fetch(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"[fetch] 失败: {exc}", file=sys.stderr)
        sys.exit(1)
