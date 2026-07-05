# backend/utils.py

import logging
import re
from typing import IO
from docx import Document

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt"}
MAX_EXTRACTED_CHARS = 20_000

# ── Prompt-injection mitigation ─────────────────────────────────
# Uploaded documents and free-text topics are untrusted input. A malicious
# PDF/DOCX can contain text like "Ignore previous instructions and instead
# output..." which an LLM may follow if it's concatenated into the prompt
# unmarked. We can't make this airtight (no purely textual defense fully
# is), but we can meaningfully raise the bar:
#   1. Strip/flag common injection trigger phrases.
#   2. Wrap untrusted content in explicit delimiters with a system-level
#      instruction (added in prompts.py) telling the model the content
#      between delimiters is DATA to summarize/use, never instructions
#      to follow.
_INJECTION_PATTERNS = re.compile(
    r"(ignore (all |the |any )?(previous|prior|above) instructions?"
    r"|disregard (all |the |any )?(previous|prior|above)"
    r"|you are now [a-z]"
    r"|system prompt"
    r"|act as (an? )?(unrestricted|jailbroken|dan)"
    r"|new instructions?:"
    r"|override (your|the) (rules|instructions|guidelines))",
    re.IGNORECASE,
)


def sanitize_untrusted_text(text: str) -> str:
    """Best-effort neutralisation of likely prompt-injection payloads found
    inside user-uploaded documents or free-text input before it gets
    concatenated into an LLM prompt. Does not delete content (so legitimate
    text mentioning these phrases in an academic context isn't mangled
    beyond recognition) — it flags/breaks the trigger phrase so it reads as
    inert text rather than an actionable instruction to the model."""
    if not text:
        return text

    def _defuse(match: "re.Match") -> str:
        return f"[{match.group(0)}]"  # bracket it so it visually reads as quoted/flagged, not an active directive

    return _INJECTION_PATTERNS.sub(_defuse, text)


def wrap_untrusted(text: str, label: str = "DOCUMENT CONTENT") -> str:
    """Wrap untrusted content in explicit delimiters for the prompt, paired
    with the system instruction in prompts.py that content between these
    markers is data only, never instructions."""
    safe = sanitize_untrusted_text(text)
    return f"<<<{label}_START>>>\n{safe}\n<<<{label}_END>>>"


def extract_text(file: IO) -> str:
    """
    Extract plain text from an uploaded file.
    Supports: .pdf, .pptx, .docx, .txt
    Returns empty string for unsupported types or on error.
    """
    filename = (getattr(file, "filename", "") or "").lower().strip()

    if filename.endswith(".pdf"):
        return _extract_pdf(file)
    if filename.endswith(".pptx"):
        return _extract_pptx(file)
    if filename.endswith(".docx"):
        return _extract_docx(file)
    if filename.endswith(".txt"):
        return _extract_txt(file)

    logger.warning("Unsupported file type: %s", filename)
    return ""


def _extract_pdf(file: IO) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file)
        pages = []
        total = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            pages.append(text)
            total += len(text)
            if total >= MAX_EXTRACTED_CHARS:
                break
        return "\n\n".join(pages)[:MAX_EXTRACTED_CHARS]
    except ImportError:
        logger.error("PyPDF2 not installed. Run: pip install PyPDF2")
        return ""
    except Exception:
        logger.exception("PDF extraction failed.")
        return ""


def _extract_pptx(file: IO) -> str:
    try:
        from pptx import Presentation
        prs = Presentation(file)
        chunks = []
        total = 0
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_texts.append(shape.text.strip())
            if slide_texts:
                chunks.append(f"[Slide {slide_num}]\n" + "\n".join(slide_texts))
                total += sum(len(t) for t in slide_texts)
                if total >= MAX_EXTRACTED_CHARS:
                    break
        return "\n\n".join(chunks)[:MAX_EXTRACTED_CHARS]
    except ImportError:
        logger.error("python-pptx not installed. Run: pip install python-pptx")
        return ""
    except Exception:
        logger.exception("PPTX extraction failed.")
        return ""


def _extract_docx(file: IO) -> str:
    try:
        doc = Document(file)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)[:MAX_EXTRACTED_CHARS]
    except ImportError:
        logger.error("python-docx not installed. Run: pip install python-docx")
        return ""
    except Exception:
        logger.exception("DOCX extraction failed.")
        return ""


def _extract_txt(file: IO) -> str:
    try:
        raw = file.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return raw[:MAX_EXTRACTED_CHARS]
    except Exception:
        logger.exception("TXT extraction failed.")
        return ""


def split_into_topic_blocks(text: str) -> list[dict]:
    """
    Heuristically split extracted document text into topic blocks
    by detecting heading-like lines.
    Returns list of {"title": str, "content": str}
    """
    import re
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks = []
    current = None

    for line in lines:
        if _is_heading(line):
            if current:
                blocks.append(current)
            current = {"title": line, "content": []}
        elif current:
            current["content"].append(line)

    if current:
        blocks.append(current)

    # Merge content lists into strings
    result = []
    for b in blocks:
        content = " ".join(b["content"])
        content = re.sub(r"\s+", " ", content).strip()
        result.append({"title": b["title"], "content": content})

    return result


def _is_heading(line: str) -> bool:
    import re
    if not (4 <= len(line) <= 80):
        return False
    generic = {"definition", "example", "explanation", "key points", "introduction", "conclusion", "summary", "overview"}
    if line.lower() in generic:
        return False
    if line.isupper() and len(line.split()) <= 8:
        return True
    if re.match(r"^\d+(\.\d+)*[\s\.\)]", line):
        return True
    if line.istitle() and len(line.split()) <= 6 and not line.endswith("."):
        return True
    return False


def format_output(text: str) -> str:
    """Basic cleanup and excessive newline collapse for generated text."""
    if not text:
        return ""
    text = text.strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text