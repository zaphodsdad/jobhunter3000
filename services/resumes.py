"""
Resume upload, storage, text extraction, and AI analysis.
"""

import json
import os
import uuid
from datetime import datetime

RESUME_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "resumes")


def save_resume(file_bytes: bytes, original_name: str) -> dict:
    """Save an uploaded resume file. Returns metadata dict."""
    os.makedirs(RESUME_DIR, exist_ok=True)

    # Generate unique filename
    ext = os.path.splitext(original_name)[1].lower()
    filename = f"{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(RESUME_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Determine file type
    type_map = {".pdf": "pdf", ".docx": "docx", ".md": "markdown", ".txt": "text"}
    file_type = type_map.get(ext, "unknown")

    return {
        "filename": filename,
        "original_name": original_name,
        "file_path": file_path,
        "file_type": file_type,
        "size": len(file_bytes),
    }


def extract_text(file_path: str, file_type: str) -> str:
    """Extract text content from a resume file."""
    if file_type == "pdf":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text.strip()
        except Exception as e:
            return f"[PDF extraction failed: {e}]"

    elif file_type == "docx":
        try:
            from docx import Document
            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs).strip()
        except Exception as e:
            return f"[DOCX extraction failed: {e}]"

    elif file_type in ("markdown", "text"):
        with open(file_path, "r", errors="replace") as f:
            return f.read().strip()

    return "[Unsupported file type]"


def analyze_resume(content_text: str, settings: dict) -> dict:
    """Use LLM to analyze a resume's strengths and target roles."""
    from services.llm import llm_chat

    prompt = """Analyze this resume and return ONLY valid JSON (no markdown fences, no explanation).

{
    "strengths": ["strength 1", "strength 2", "strength 3"],
    "target_roles": ["role type 1", "role type 2", "role type 3"],
    "experience_level": "entry/mid/senior/executive",
    "industries": ["industry 1", "industry 2"],
    "key_skills": ["skill 1", "skill 2", "skill 3", "skill 4", "skill 5"],
    "gaps": ["gap or weakness 1", "gap 2"],
    "summary": "One sentence summary of this candidate's profile"
}

RESUME:
""" + content_text[:6000]  # Limit to avoid token overflow

    result = llm_chat(
        [{"role": "user", "content": prompt}],
        settings,
    )

    # Parse JSON from response
    try:
        # Strip markdown fences if present
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "strengths": [],
            "target_roles": [],
            "experience_level": "unknown",
            "industries": [],
            "key_skills": [],
            "gaps": [],
            "summary": result[:200],
            "raw_response": result,
        }


def insert_resume(conn, metadata: dict, content_text: str) -> int:
    """Insert a resume record into the database."""
    cursor = conn.execute(
        """INSERT INTO resumes (filename, original_name, file_path, file_type, content_text, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            metadata["filename"],
            metadata["original_name"],
            metadata["file_path"],
            metadata["file_type"],
            content_text,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_resumes(conn) -> list[dict]:
    """Get all resumes."""
    rows = conn.execute(
        "SELECT * FROM resumes ORDER BY uploaded_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_resume(conn, resume_id: int) -> dict | None:
    """Get a single resume by ID."""
    row = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    return dict(row) if row else None


def update_resume_analysis(conn, resume_id: int, analysis: dict) -> bool:
    """Store analysis results on a resume."""
    best_for = analysis.get("target_roles", [])
    conn.execute(
        "UPDATE resumes SET analysis = ?, best_for = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(best_for), resume_id),
    )
    conn.commit()
    return True


def delete_resume(conn, resume_id: int) -> bool:
    """Delete a resume record and file."""
    resume = get_resume(conn, resume_id)
    if not resume:
        return False
    # Delete file
    if resume["file_path"] and os.path.exists(resume["file_path"]):
        os.remove(resume["file_path"])
    conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
    conn.commit()
    return True
