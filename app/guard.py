"""R7/R8 helpers: redaction for logs, instruction-like text detection in untrusted content."""
import re

INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above) (instructions|rules)|disregard .{0,30}(instructions|policy)"
    r"|you are now|act as (an? )?(admin|system)|system prompt|new instructions?:|developer mode"
    r"|approve (a |the |this )?(full )?refund|issue (a )?(full )?refund|override .{0,20}(policy|rule)"
    r"|reveal .{0,30}(customer|order|data)|<\s*/?\s*system\s*>)",
    re.I,
)
PII = [(re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
       (re.compile(r"(?<!\w)(?:\+91[-\s]?)?[6-9]\d{9}(?!\w)"), "[phone]"),
       (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card]")]


def redact(text: str) -> str:
    for pat, rep in PII:
        text = pat.sub(rep, text)
    return text


def flag_injection(text: str) -> bool:
    return bool(INJECTION.search(text or ""))


def sanitize_evidence(text: str) -> tuple[str, bool]:
    """Neutralise instruction-like lines inside retrieved content before the LLM sees it."""
    flagged = False
    out = []
    for line in text.splitlines():
        if INJECTION.search(line):
            flagged = True
            out.append("[removed: instruction-like text in source, treated as data]")
        else:
            out.append(line)
    return "\n".join(out), flagged
