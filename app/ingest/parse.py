"""File -> list of Block(page, section, text). Sections are what citations point at."""
import re
from dataclasses import dataclass
from pathlib import Path

# "3.1 Electronics", "3.1. Electronics", "Section 4", "Clause 2.3", "## Returns"
HEADING = re.compile(
    r"^\s*(?:#{1,4}\s*)?(?:(?:section|clause|§)\s*)?(\d+(?:\.\d+){0,3})[.)]?\s+(\S.{0,90})$",
    re.IGNORECASE,
)
MD_HEADING = re.compile(r"^\s*#{1,4}\s+(.{1,100})$")


@dataclass
class Block:
    page: int
    section: str
    heading: str
    text: str


def _split_sections(lines: list[tuple[int, str]]) -> list[Block]:
    blocks: list[Block] = []
    cur_sec, cur_head, cur_page, buf = "0", "Preamble", 1, []

    def flush():
        txt = "\n".join(buf).strip()
        if txt:
            blocks.append(Block(cur_page, cur_sec, cur_head, txt))

    for page, line in lines:
        m = HEADING.match(line)
        md = MD_HEADING.match(line) if not m else None
        if (m and len(line) < 110) or md:
            flush()
            buf = []
            if m:
                cur_sec, cur_head = m.group(1), m.group(2).strip()
            else:
                cur_head = md.group(1).strip()
                cur_sec = cur_head[:40]
            cur_page = page
            buf.append(line.strip())
            continue
        if not buf:
            cur_page = page
        buf.append(line)
    flush()
    return blocks


def _pdf(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    from pypdf import PdfReader
    warns, lines = [], []
    for i, pg in enumerate(PdfReader(str(path)).pages, start=1):
        txt = pg.extract_text() or ""
        if len(txt.strip()) < 20:
            txt = _ocr_page(path, i, warns)
        lines += [(i, ln) for ln in txt.splitlines()]
    return lines, warns


def _ocr_page(path: Path, page_no: int, warns: list[str]) -> str:
    """Scanned page -> OCR. Needs tesseract + pdf2image installed; degrades to a warning."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
        img = convert_from_path(str(path), first_page=page_no, last_page=page_no, dpi=300)[0]
        return pytesseract.image_to_string(img)
    except Exception as e:
        warns.append(f"page {page_no}: no text layer and OCR unavailable ({type(e).__name__})")
        return ""


def _docx(path: Path) -> list[tuple[int, str]]:
    import docx
    d = docx.Document(str(path))
    lines: list[tuple[int, str]] = []
    body = d.element.body
    # walk paragraphs and tables in document order so tables stay inside their section
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = docx.text.paragraph.Paragraph(child, d)
            t = p.text.strip()
            if not t:
                continue
            if p.style is not None and p.style.name.lower().startswith("heading") and not HEADING.match(t):
                t = f"## {t}"
            lines.append((1, t))
        elif tag == "tbl":
            tbl = docx.table.Table(child, d)
            for row in tbl.rows:
                cells = [c.text.strip() for c in row.cells]
                lines.append((1, " | ".join(cells)))
    return lines


def parse(path: Path) -> tuple[list[Block], list[str]]:
    ext = path.suffix.lower()
    warns: list[str] = []
    if ext == ".pdf":
        lines, warns = _pdf(path)
    elif ext == ".docx":
        lines = _docx(path)
    elif ext in {".md", ".txt", ".markdown"}:
        lines = [(1, ln) for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
        # form feed or "--- page N ---" markers let plain-text docs carry page numbers
        page, out = 1, []
        for _, ln in lines:
            if "\f" in ln or re.match(r"^\s*-{2,}\s*page\s*(\d+)", ln, re.I):
                m = re.search(r"(\d+)", ln)
                page = int(m.group(1)) if m else page + 1
                continue
            out.append((page, ln))
        lines = out
    elif ext in {".png", ".jpg", ".jpeg"}:
        try:
            import pytesseract
            from PIL import Image
            lines = [(1, ln) for ln in pytesseract.image_to_string(Image.open(path)).splitlines()]
        except Exception as e:
            lines, warns = [], [f"image OCR unavailable ({type(e).__name__})"]
    else:
        raise ValueError(f"unsupported file type: {ext}")
    return _split_sections(lines), warns
