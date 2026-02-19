"""
JobHunter3000 — Job search operations center.
Run: python3 app.py
Browse: http://localhost:8001
"""

import json
import os
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn

from services.settings import load_settings, save_settings
from services.db import (
    get_db, ensure_tables, get_dashboard_stats, get_jobs, get_job,
    update_job_status, update_job, get_sources, get_statuses,
)

app = FastAPI(title="JobHunter3000")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/resumes", exist_ok=True)
    os.makedirs("data/cover-letters", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    conn = get_db()
    ensure_tables(conn)
    conn.close()


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    conn = get_db()
    stats = get_dashboard_stats(conn)
    conn.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
    })


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request,
                    status: Optional[str] = None,
                    source: Optional[str] = None,
                    sort: Optional[str] = "created_at",
                    order: Optional[str] = "desc"):
    conn = get_db()
    jobs = get_jobs(conn, status=status, source=source, sort=sort, order=order)
    statuses = get_statuses(conn)
    sources = get_sources(conn)
    conn.close()
    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": jobs,
        "statuses": statuses,
        "sources": sources,
        "current_status": status or "",
        "current_source": source or "",
        "current_sort": sort,
        "current_order": order,
    })


@app.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    conn = get_db()
    # Group jobs by status
    all_jobs = get_jobs(conn, limit=500)
    conn.close()

    pipeline = {
        "new": [],
        "interested": [],
        "applied": [],
        "interviewing": [],
        "offer": [],
    }
    rejected = []

    for job in all_jobs:
        s = job.get("status", "new")
        if s == "rejected":
            rejected.append(job)
        elif s in pipeline:
            pipeline[s].append(job)
        elif s == "accepted":
            pipeline["offer"].append(job)

    return templates.TemplateResponse("pipeline.html", {
        "request": request,
        "pipeline": pipeline,
        "rejected": rejected,
    })


@app.get("/resumes", response_class=HTMLResponse)
async def resumes_page(request: Request):
    from services.resumes import get_resumes
    conn = get_db()
    resumes = get_resumes(conn)
    conn.close()
    return templates.TemplateResponse("resumes.html", {
        "request": request,
        "resumes": resumes,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: Optional[str] = None):
    settings = load_settings()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "saved": saved == "1",
    })


@app.post("/settings")
async def save_settings_route(request: Request):
    form = await request.form()
    data = dict(form)

    # Handle exclude_keywords textarea -> list
    if "exclude_keywords" in data:
        kw = data["exclude_keywords"]
        if isinstance(kw, str):
            data["exclude_keywords"] = [k.strip() for k in kw.split("\n") if k.strip()]

    # Handle numeric fields
    for field in ("notify_threshold", "priority_threshold", "max_days_old", "scrape_interval_hours"):
        if field in data:
            try:
                data[field] = int(data[field])
            except (ValueError, TypeError):
                pass

    save_settings(data)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
async def api_get_jobs(status: Optional[str] = None,
                       source: Optional[str] = None,
                       sort: Optional[str] = "created_at",
                       order: Optional[str] = "desc",
                       limit: int = 100, offset: int = 0):
    conn = get_db()
    jobs = get_jobs(conn, status=status, source=source, sort=sort, order=order,
                    limit=limit, offset=offset)
    conn.close()
    return JSONResponse(jobs)


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: int):
    conn = get_db()
    job = get_job(conn, job_id)
    conn.close()
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse(job)


@app.post("/api/jobs/{job_id}/status")
async def api_update_status(job_id: int, request: Request):
    body = await request.json()
    new_status = body.get("status", "").strip()
    conn = get_db()
    success = update_job_status(conn, job_id, new_status)
    conn.close()
    if not success:
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    return JSONResponse({"ok": True, "status": new_status})


@app.post("/api/jobs/{job_id}/notes")
async def api_update_notes(job_id: int, request: Request):
    body = await request.json()
    notes = body.get("notes", "")
    conn = get_db()
    success = update_job(conn, job_id, {"notes": notes})
    conn.close()
    if not success:
        return JSONResponse({"error": "Failed to update"}, status_code=400)
    return JSONResponse({"ok": True})


@app.get("/api/stats")
async def api_stats():
    conn = get_db()
    stats = get_dashboard_stats(conn)
    conn.close()
    return JSONResponse(stats)


@app.get("/api/settings")
async def api_get_settings():
    settings = load_settings()
    # Mask API keys for security
    if settings.get("openrouter_api_key"):
        key = settings["openrouter_api_key"]
        settings["openrouter_api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    if settings.get("pushover_api_token"):
        token = settings["pushover_api_token"]
        settings["pushover_api_token"] = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
    return JSONResponse(settings)


@app.post("/api/test-llm")
async def api_test_llm():
    """Test the LLM connection."""
    settings = load_settings()
    try:
        from services.llm import llm_chat
        result = llm_chat(
            [{"role": "user", "content": "Say 'JobHunter3000 connected!' and nothing else."}],
            settings,
        )
        return JSONResponse({"ok": True, "response": result.strip()})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/test-notify")
async def api_test_notify():
    """Send a test Pushover notification."""
    settings = load_settings()
    try:
        import requests
        resp = requests.post("https://api.pushover.net/1/messages.json", data={
            "token": settings.get("pushover_api_token", ""),
            "user": settings.get("pushover_user_key", ""),
            "title": "JobHunter3000 Test",
            "message": "Notifications are working!",
        })
        if resp.status_code == 200:
            return JSONResponse({"ok": True})
        else:
            return JSONResponse({"ok": False, "error": resp.text}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/import")
async def api_import_spreadsheet():
    """Re-import the spreadsheet data."""
    spreadsheet = os.path.join(os.path.dirname(__file__), "tests", "Job Search.xlsx")
    if not os.path.exists(spreadsheet):
        return JSONResponse({"error": "Spreadsheet not found"}, status_code=404)

    from services.importer import import_spreadsheet, insert_imported_jobs
    conn = get_db()
    jobs = import_spreadsheet(spreadsheet)
    result = insert_imported_jobs(conn, jobs)
    conn.close()
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Resume APIs
# ---------------------------------------------------------------------------

@app.post("/api/resumes/upload")
async def api_upload_resume(file: UploadFile = File(...)):
    """Upload a resume file."""
    from services.resumes import save_resume, extract_text, insert_resume

    allowed = {".pdf", ".docx", ".md", ".txt"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        return JSONResponse(
            {"error": f"Unsupported file type: {ext}. Use PDF, DOCX, MD, or TXT."},
            status_code=400,
        )

    contents = await file.read()
    metadata = save_resume(contents, file.filename)
    content_text = extract_text(metadata["file_path"], metadata["file_type"])

    conn = get_db()
    resume_id = insert_resume(conn, metadata, content_text)
    conn.close()

    return JSONResponse({"ok": True, "id": resume_id, "filename": metadata["filename"]})


@app.post("/api/resumes/{resume_id}/analyze")
async def api_analyze_resume(resume_id: int):
    """Run LLM analysis on a resume."""
    from services.resumes import get_resume, analyze_resume, update_resume_analysis

    conn = get_db()
    resume = get_resume(conn, resume_id)
    if not resume:
        conn.close()
        return JSONResponse({"error": "Resume not found"}, status_code=404)

    if not resume["content_text"]:
        conn.close()
        return JSONResponse({"error": "No text content extracted from resume"}, status_code=400)

    settings = load_settings()
    try:
        analysis = analyze_resume(resume["content_text"], settings)
        update_resume_analysis(conn, resume_id, analysis)
        conn.close()
        return JSONResponse({"ok": True, "analysis": analysis})
    except Exception as e:
        conn.close()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/resumes")
async def api_list_resumes():
    """List all resumes."""
    from services.resumes import get_resumes
    conn = get_db()
    resumes = get_resumes(conn)
    conn.close()
    return JSONResponse(resumes)


@app.delete("/api/resumes/{resume_id}")
async def api_delete_resume(resume_id: int):
    """Delete a resume."""
    from services.resumes import delete_resume
    conn = get_db()
    success = delete_resume(conn, resume_id)
    conn.close()
    if not success:
        return JSONResponse({"error": "Resume not found"}, status_code=404)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
