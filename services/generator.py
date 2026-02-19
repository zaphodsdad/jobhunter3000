"""
Resume & cover letter generation — tailored to specific job postings using LLM.
"""

import json
import os
import re
import sqlite3
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from services.llm import llm_chat
from services.resumes import load_candidate_profile
from services.settings import load_settings

GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "generated")


def _md_to_docx(markdown: str, output_path: str, doc_type: str = "resume"):
    """Convert markdown text to a clean .docx file."""
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    # Tighter paragraph spacing
    style.paragraph_format.space_after = Pt(4)
    style.paragraph_format.space_before = Pt(0)

    # Set narrow margins
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Horizontal rule → thin line (skip it, just adds spacing)
        if stripped in ("---", "***", "___"):
            i += 1
            continue

        # H1: # Header
        if stripped.startswith("# ") and not stripped.startswith("## "):
            text = stripped[2:].strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # strip bold markers
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(text)
            run.bold = True
            run.font.size = Pt(16)
            run.font.color.rgb = RGBColor(0x1a, 0x1a, 0x1a)
            p.paragraph_format.space_after = Pt(2)
            i += 1
            continue

        # H2: ## Section Header
        if stripped.startswith("## "):
            text = stripped[3:].strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            p = doc.add_paragraph()
            run = p.add_run(text.upper())
            run.bold = True
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0x1a, 0x56, 0x8a)
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(3)
            # Add a bottom border
            from docx.oxml.ns import qn
            pPr = p._p.get_or_add_pPr()
            pBdr = pPr.makeelement(qn("w:pBdr"), {})
            bottom = pBdr.makeelement(qn("w:bottom"), {
                qn("w:val"): "single",
                qn("w:sz"): "4",
                qn("w:space"): "1",
                qn("w:color"): "1a568a",
            })
            pBdr.append(bottom)
            pPr.append(pBdr)
            i += 1
            continue

        # H3: ### Sub-header
        if stripped.startswith("### "):
            text = stripped[4:].strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            p = doc.add_paragraph()
            run = p.add_run(text)
            run.bold = True
            run.font.size = Pt(11)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(2)
            i += 1
            continue

        # Bullet point: - text or * text
        if re.match(r"^[-*]\s", stripped):
            text = stripped[2:].strip()
            p = doc.add_paragraph(style="List Bullet")
            _add_formatted_text(p, text)
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.left_indent = Inches(0.25)
            i += 1
            continue

        # Regular paragraph (handle bold/italic inline)
        p = doc.add_paragraph()
        _add_formatted_text(p, stripped)
        # Center lines that look like contact info (short, contain | or email)
        if len(stripped) < 120 and ("|" in stripped or "@" in stripped):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(1)
        i += 1

    doc.save(output_path)


def _add_formatted_text(paragraph, text):
    """Add text to a paragraph, handling **bold** and *italic* markers."""
    # Split on bold markers first
    parts = re.split(r"(\*\*[^*]+?\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif "*" in part:
            # Handle italic within non-bold segments
            sub_parts = re.split(r"(\*[^*]+?\*)", part)
            for sp in sub_parts:
                if sp.startswith("*") and sp.endswith("*"):
                    run = paragraph.add_run(sp[1:-1])
                    run.italic = True
                else:
                    if sp:
                        paragraph.add_run(sp)
        else:
            if part:
                paragraph.add_run(part)


def _pick_best_resume(job: dict) -> tuple[str, str]:
    """Pick the best-matching uploaded resume for a job.

    Compares each resume's best_for tags against the job title/description.
    Returns (content_text, original_name) of the best match.
    Falls back to the longest resume if no tag matches.
    """
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "jobs.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT original_name, content_text, best_for FROM resumes WHERE content_text IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        return "", ""

    job_text = f"{job.get('title', '')} {job.get('description', '')}".lower()

    best_score = -1
    best_row = None
    longest_row = None
    longest_len = 0

    for row in rows:
        text = row["content_text"] or ""

        # Track longest as fallback
        if len(text) > longest_len:
            longest_len = len(text)
            longest_row = row

        # Score by best_for tag overlap
        best_for = row["best_for"]
        if best_for:
            try:
                tags = json.loads(best_for) if isinstance(best_for, str) else best_for
            except (json.JSONDecodeError, TypeError):
                tags = []

            score = 0
            for tag in tags:
                # Check if any word from the tag appears in job text
                tag_words = tag.lower().split()
                for word in tag_words:
                    if len(word) > 3 and word in job_text:
                        score += 1
            if score > best_score:
                best_score = score
                best_row = row

    chosen = best_row if best_score > 0 else longest_row
    if chosen:
        return chosen["content_text"], chosen["original_name"]
    return "", ""


def generate_resume(job: dict, settings: dict = None) -> dict:
    """Generate a tailored resume for a specific job posting.

    Returns {ok, markdown, path, resume_source} or {error}.
    """
    if not settings:
        settings = load_settings()

    profile = load_candidate_profile()
    if not profile:
        return {"error": "No candidate profile. Analyze resumes first."}

    resume_text, resume_name = _pick_best_resume(job)
    if not resume_text:
        return {"error": "No resumes uploaded. Upload resumes in Arsenal first."}

    job_info = (
        f"Title: {job.get('title', 'Unknown')}\n"
        f"Company: {job.get('company', 'Unknown')}\n"
        f"Location: {job.get('location', 'Unknown')}\n"
        f"Industry: {job.get('industry', 'Unknown')}\n"
        f"Salary: {job.get('salary_text', 'Not listed')}\n"
        f"Description:\n{(job.get('description', '') or '')[:4000]}"
    )

    prompt = f"""You are an expert resume writer. Create a tailored resume for this specific job posting.

CANDIDATE PROFILE:
Name: {profile.get('name', 'Unknown')}
Headline: {profile.get('headline', '')}
Experience: {profile.get('experience_years', 0)}+ years
Core Strengths: {', '.join(profile.get('core_strengths', []))}
Key Skills: {', '.join(profile.get('all_skills', [])[:25])}
Unique Value: {profile.get('unique_value', '')}

SOURCE RESUME (use this as the base — reorder, emphasize, and tailor):
{resume_text[:5000]}

TARGET JOB:
{job_info}

INSTRUCTIONS:
- Tailor this resume specifically for the job above
- Lead with the most relevant experience and skills for THIS role
- Use keywords and phrases from the job description naturally
- Keep it to 1-2 pages worth of content
- Use clean markdown formatting with clear sections
- Include: Contact header, Professional Summary (tailored), Key Skills (relevant ones first), Professional Experience (reordered by relevance), Education
- Do NOT fabricate experience or skills — only reorganize and emphasize what's real
- Make the professional summary directly address what this employer is looking for

Output the resume in clean markdown. No commentary before or after — just the resume."""

    result = llm_chat(
        [{"role": "user", "content": prompt}],
        settings,
    )

    # Save markdown
    os.makedirs(GENERATED_DIR, exist_ok=True)
    md_filename = f"{job['id']}_resume.md"
    md_path = os.path.join(GENERATED_DIR, md_filename)
    with open(md_path, "w") as f:
        f.write(result)

    # Convert to DOCX
    docx_filename = f"{job['id']}_resume.docx"
    docx_path = os.path.join(GENERATED_DIR, docx_filename)
    _md_to_docx(result, docx_path, doc_type="resume")

    # Update job record
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "jobs.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE jobs SET resume_path = ?, updated_at = datetime('now') WHERE id = ?",
        (docx_path, job["id"]),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "markdown": result,
        "path": docx_path,
        "docx_filename": docx_filename,
        "resume_source": resume_name,
    }


def generate_cover_letter(job: dict, settings: dict = None) -> dict:
    """Generate a tailored cover letter for a specific job posting.

    Returns {ok, markdown, path} or {error}.
    """
    if not settings:
        settings = load_settings()

    profile = load_candidate_profile()
    if not profile:
        return {"error": "No candidate profile. Analyze resumes first."}

    elevator_pitch = settings.get("candidate_elevator_pitch", "")

    job_info = (
        f"Title: {job.get('title', 'Unknown')}\n"
        f"Company: {job.get('company', 'Unknown')}\n"
        f"Location: {job.get('location', 'Unknown')}\n"
        f"Description:\n{(job.get('description', '') or '')[:4000]}"
    )

    work_history = ""
    for wh in profile.get("work_history", [])[:5]:
        highlights = "; ".join(wh.get("highlights", [])[:2])
        work_history += f"- {wh['title']} @ {wh['company']} ({wh['duration']}): {highlights}\n"

    prompt = f"""You are an expert career coach and cover letter writer. Write a professional, compelling cover letter for this specific job.

CANDIDATE:
Name: {profile.get('name', 'Unknown')}
Headline: {profile.get('headline', '')}
Experience: {profile.get('experience_years', 0)}+ years
Core Strengths: {', '.join(profile.get('core_strengths', []))}
Key Skills: {', '.join(profile.get('all_skills', [])[:20])}
Unique Value: {profile.get('unique_value', '')}
{f'Elevator Pitch: {elevator_pitch}' if elevator_pitch else ''}

RELEVANT WORK HISTORY:
{work_history}

TARGET JOB:
{job_info}

INSTRUCTIONS:
- Write a professional cover letter (3-4 paragraphs)
- Opening: Hook that shows you understand what this company/role needs
- Body: Connect 2-3 specific experiences to what the job requires — be concrete, not generic
- Closing: Confident but not arrogant, express genuine interest, call to action
- Tone: Professional, direct, personable — not stuffy corporate-speak
- Do NOT use cliches like "I'm writing to express my interest" or "I believe I would be an asset"
- Do NOT fabricate anything — only reference real experience from the profile
- Keep it under 400 words
- Use markdown formatting

Output only the cover letter. No commentary before or after."""

    result = llm_chat(
        [{"role": "user", "content": prompt}],
        settings,
    )

    # Save markdown
    os.makedirs(GENERATED_DIR, exist_ok=True)
    md_filename = f"{job['id']}_cover.md"
    md_path = os.path.join(GENERATED_DIR, md_filename)
    with open(md_path, "w") as f:
        f.write(result)

    # Convert to DOCX
    docx_filename = f"{job['id']}_cover.docx"
    docx_path = os.path.join(GENERATED_DIR, docx_filename)
    _md_to_docx(result, docx_path, doc_type="cover")

    # Update job record
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "jobs.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE jobs SET cover_letter_path = ?, updated_at = datetime('now') WHERE id = ?",
        (docx_path, job["id"]),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "markdown": result,
        "path": docx_path,
        "docx_filename": docx_filename,
    }
