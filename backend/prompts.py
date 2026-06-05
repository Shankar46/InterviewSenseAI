# backend/prompts.py


def _notes_length(mode: str) -> str:
    return {
        "2 Marks": """
STRICT OUTPUT FORMAT:
- Generate ONLY a short university exam answer worth 2 marks.
- Maximum 80 words total.
- Structure:
    1. One crisp definition sentence.
    2. Exactly 2 bullet points supporting the definition.
- DO NOT include: introduction, conclusion, tables, report/research/assignment formatting.
""",
        "5 Marks": """
STRICT OUTPUT FORMAT:
- Generate ONLY a medium university exam answer worth 5 marks.
- Maximum 200 words total.
- Structure:
    1. Definition (1–2 sentences).
    2. Core concept explanation (2–3 sentences).
    3. Exactly 4 bullet points covering key features / advantages.
- DO NOT include: executive summary, abstract, research methodology,
  literature survey, assignment title page, or report sections.
""",
        "10 Marks": """
STRICT OUTPUT FORMAT:
- Generate ONLY a detailed university exam answer worth 10 marks.
- Target length: 600–800 words.
- Mandatory headings (use Markdown ##):
    ## Introduction
    ## Core Concept / Definition
    ## Working Principle / Architecture / Mechanism
    ## Advantages
    ## Limitations
    ## Real-World Applications
    ## Conclusion
- Use academic exam-writing style with bullet points under each heading where appropriate.

STRICTLY FORBIDDEN:
Executive Summary, Abstract, Literature Review, Methodology,
Research Paper Formatting, Bibliography, References, Assignment Submission Style.
""",
    }.get(mode, "")


def _task_system(task: str) -> str:
    systems = {
        "notes": """
ROLE: Elite university exam preparation assistant.
OBJECTIVE: Generate ONLY exam-oriented notes and direct answers.
RULES:
- No reports, research papers, assignments, executive summaries, abstracts,
  methodologies, references, or citations.
- Exam-focused, concise, academic, scoring-oriented, student-friendly.
- Return ONLY the answer content.
""",
        "assignment": """
ROLE: Professional academic assignment writer.
OBJECTIVE: Generate a properly formatted university assignment.
MANDATORY STRUCTURE:
  1. Title
  2. Introduction
  3. Main Body (with sub-headings)
  4. Conclusion
RULES:
- Formal academic tone, paragraph-based prose, well-structured.
- No report formatting, no research paper structure, no exam-style short answers.
- Return ONLY assignment content.
""",
        "report": """
ROLE: Professional technical report writer.
OBJECTIVE: Generate a formal, professional report.
MANDATORY STRUCTURE:
  1. Title
  2. Executive Summary
  3. Introduction
  4. Objectives
  5. Findings / Analysis
  6. Recommendations
  7. Conclusion
RULES:
- Corporate, professional, analytical tone.
- No exam answers, no notes, no assignment or research paper formatting.
- Return ONLY report content.
""",
        "research": """
ROLE: Academic research paper generator.
OBJECTIVE: Generate research-oriented academic content.
MANDATORY STRUCTURE:
  1. Title
  2. Abstract
  3. Introduction
  4. Literature Review
  5. Methodology
  6. Analysis / Discussion
  7. Conclusion
  8. Future Scope
RULES:
- Scholarly, technical, research-oriented, analytical.
- No report formatting, no exam answers, no short notes or assignments.
- Return ONLY research paper content.
""",
        "explainer": """
ROLE: Expert teacher and concept explainer.
OBJECTIVE: Explain concepts clearly, step by step, in plain language.
RULES:
- Teacher-like, beginner-friendly, step-by-step with real-world examples.
- No reports, no assignments, no research papers.
- No exam-style answers unless explicitly requested.
- Return ONLY the explanation.
""",
        "review": """
ROLE: Academic and professional document reviewer.
OBJECTIVE: Review and evaluate the provided content.
CHECK FOR: Grammar, Structure, Clarity, Formatting, Professionalism,
           Technical correctness, Logical flow.
OUTPUT STRUCTURE:
  1. Overall Evaluation
  2. Strengths
  3. Weaknesses
  4. Improvement Suggestions
  5. Grammar / Structure Issues
RULES:
- Do NOT rewrite the full document unless asked.
- Provide review feedback only.
""",
    }
    return systems.get(task, systems["notes"])


def _format_history(history: list) -> str:
    if not history:
        return "None"
    lines = []
    for item in history[-3:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "")
        content = (item.get("content") or "").strip()
        if role and content:
            lines.append(f"{role}: {content[:600]}")
    return "\n".join(lines) or "None"


def get_prompt(task: str, topic: str, mode: str = None, history: list = None, file_text: str = None) -> str:
    context = (file_text or "").strip() or "No reference document provided."
    history_block = _format_history(history or [])
    length_instruction = _notes_length(mode) if task == "notes" and mode else ""

    return f"""{_task_system(task)}

══════════════════════════════════════════
USER TOPIC / QUESTION:
{topic}

══════════════════════════════════════════
REFERENCE DOCUMENT CONTEXT:
{context}

══════════════════════════════════════════
RECENT CONVERSATION HISTORY:
{history_block}

══════════════════════════════════════════
GLOBAL OUTPUT RULES:
- Rely primarily on the reference document context when available.
- If the document is insufficient, draw on accurate academic knowledge.
- Never fabricate facts, statistics, or references.
- Never mix task formats (e.g. do not write exam notes when asked for a report).
- Never output filler phrases like "Sure!", "Here is your answer", or "I hope this helps".
- Stay strictly within the role and format defined above.
{length_instruction}
══════════════════════════════════════════
Return ONLY the final formatted output. No meta-commentary.
"""