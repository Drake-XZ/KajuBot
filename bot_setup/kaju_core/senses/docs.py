"""读文字文件：纯文本（txt/md/字幕/代码…）、网页、Word(.docx)、PDF、电子书(.epub)。

只用 AstrBot 环境里已有的库（pypdf、python-docx、bs4、charset_normalizer），不依赖 AstrBot 本身，方便离线测试。
扫描版 PDF（整页是图片）读不出字，返回空文本。老的 .doc、压缩包、程序等不认识的文件返回 None。
"""

from __future__ import annotations

import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json", ".srt", ".lrc", ".ass", ".vtt", ".ini", ".cfg",
    ".conf", ".toml", ".yaml", ".yml", ".xml", ".tex", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs",
    ".go", ".rs", ".sql", ".sh", ".bat", ".ps1", ".lua", ".rb", ".php", ".kt", ".swift",
}
KINDS = {".html": "html", ".htm": "html", ".xhtml": "html", ".docx": "docx", ".pdf": "pdf", ".epub": "epub"}


def doc_kind(name: str) -> str | None:
    """'text' / 'html' / 'docx' / 'pdf' / 'epub'，不认识的返回 None。"""
    ext = os.path.splitext((name or "").split("?", 1)[0])[1].lower()
    if ext in TEXT_EXTS:
        return "text"
    return KINDS.get(ext)


def decode(data: bytes) -> str:
    """UTF-8（含 BOM）→ GB18030（中文 Windows 记事本常见）→ 自动猜。"""
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except Exception:  # noqa: BLE001
        pass
    return data.decode("utf-8", "replace")


def tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("　", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _html_text(markup: bytes | str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    return soup.get_text("\n")


def _docx(path: str, max_chars: int) -> str:
    import docx

    d = docx.Document(path)
    out, n = [], 0
    for p in d.paragraphs:
        out.append(p.text)
        n += len(p.text)
        if n > max_chars:
            return "\n".join(out)
    for table in d.tables:
        for row in table.rows:
            out.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(out)


def _pdf(path: str, max_chars: int, max_pages: int) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    out, n = [], 0
    for i, page in enumerate(reader.pages):
        if i >= max_pages or n > max_chars:
            break
        t = page.extract_text() or ""
        out.append(t)
        n += len(t)
    return "\n".join(out), len(reader.pages)


def _epub(path: str, max_chars: int) -> str:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        order: list[str] = []
        try:
            root = ET.fromstring(z.read("META-INF/container.xml"))
            opf = next(el.get("full-path") for el in root.iter() if el.tag.endswith("rootfile"))
            pkg = ET.fromstring(z.read(opf))
            base = posixpath.dirname(opf)
            items = {el.get("id"): el.get("href") for el in pkg.iter() if el.tag.endswith("}item") or el.tag == "item"}
            for ref in (el for el in pkg.iter() if el.tag.endswith("itemref")):
                href = items.get(ref.get("idref"))
                if href:
                    full = posixpath.normpath(posixpath.join(base, href.split("#", 1)[0]))
                    if full in names:
                        order.append(full)
        except Exception:  # noqa: BLE001 — 目录坏了就按文件名顺序读
            order = []
        if not order:
            order = sorted(n for n in names if n.lower().endswith((".xhtml", ".html", ".htm")))
        out, n = [], 0
        for name in order:
            t = _html_text(z.read(name))
            out.append(t)
            n += len(t)
            if n > max_chars:
                break
        return "\n".join(out)


def read(path: str, kind: str, max_chars: int = 200_000, max_pages: int = 400) -> tuple[str, str]:
    """Extract text. Returns (text, info) where info is a short note like "共 12 页"; text may be ''."""
    info = ""
    if kind == "text":
        with open(path, "rb") as f:
            text = decode(f.read(max_chars * 4))
    elif kind == "html":
        with open(path, "rb") as f:
            text = _html_text(f.read(max_chars * 8))
    elif kind == "docx":
        text = _docx(path, max_chars)
    elif kind == "pdf":
        text, pages = _pdf(path, max_chars, max_pages)
        info = f"共 {pages} 页"
    elif kind == "epub":
        text = _epub(path, max_chars)
    else:
        raise ValueError(f"不认识的文件类型 {kind}")
    return tidy(text)[:max_chars], info


def clip(text: str, budget: int) -> str:
    """太长时留开头七成、结尾三成（故事的结局、文章的结论常在最后）。"""
    if len(text) <= budget:
        return text
    head, tail = int(budget * 0.7), int(budget * 0.3)
    return f"{text[:head]}\n……（中间省略约 {len(text) - head - tail} 字）……\n{text[-tail:]}"


def excerpt(text: str, n: int) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n] + "…"
