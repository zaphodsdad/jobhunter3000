"""
JobHunter3000 — Job search operations center.
Run: python3 app.py
Browse: http://localhost:8001
"""

import json
import os
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
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
    os.makedirs("data/generated", exist_ok=True)
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
                    sort: Optional[str] = "score",
                    order: Optional[str] = "desc"):
    conn = get_db()
    jobs = get_jobs(conn, status=status, source=source, sort=sort, order=order)
    statuses = get_statuses(conn)
    sources = get_sources(conn)
    conn.close()

    # Parse JSON fields for template rendering
    for job in jobs:
        for field in ("pros", "cons"):
            val = job.get(field)
            if isinstance(val, str):
                try:
                    job[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    job[field] = []

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


@app.get("/scraper", response_class=HTMLResponse)
async def scraper_page(request: Request):
    settings = load_settings()
    conn = get_db()
    runs = conn.execute(
        "SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse("scraper.html", {
        "request": request,
        "search_profiles": settings.get("search_profiles", []),
        "runs": [dict(r) for r in runs],
    })


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, saved: Optional[str] = None):
    from services.resumes import load_candidate_profile
    settings = load_settings()
    profile = load_candidate_profile()
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "settings": settings,
        "profile": profile,
        "saved": saved == "1",
    })


@app.post("/profile")
async def save_profile_route(request: Request):
    form = await request.form()
    data = dict(form)

    # Convert tag fields (|||‐delimited) back to lists
    for field in ("candidate_target_roles", "candidate_target_industries",
                  "candidate_dealbreakers", "candidate_nice_to_haves"):
        if field in data:
            raw = data[field]
            if isinstance(raw, str):
                data[field] = [v.strip() for v in raw.split("|||") if v.strip()]
            else:
                data[field] = []

    # Numeric fields
    for field in ("candidate_radius_miles", "candidate_salary_min",
                  "candidate_salary_max", "candidate_willing_to_travel"):
        if field in data:
            try:
                data[field] = int(data[field])
            except (ValueError, TypeError):
                pass

    save_settings(data)
    return RedirectResponse(url="/profile?saved=1", status_code=303)


@app.get("/resumes", response_class=HTMLResponse)
async def resumes_page(request: Request):
    from services.resumes import get_resumes, load_candidate_profile
    conn = get_db()
    resumes = get_resumes(conn)
    conn.close()
    profile = load_candidate_profile()
    return templates.TemplateResponse("resumes.html", {
        "request": request,
        "resumes": resumes,
        "profile": profile,
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
    if settings.get("google_api_key"):
        gkey = settings["google_api_key"]
        settings["google_api_key"] = gkey[:8] + "..." + gkey[-4:] if len(gkey) > 12 else "***"
    if settings.get("pushover_api_token"):
        token = settings["pushover_api_token"]
        settings["pushover_api_token"] = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
    return JSONResponse(settings)


@app.post("/api/test-llm")
async def api_test_llm():
    """Test the LLM connection."""
    import asyncio
    settings = load_settings()
    try:
        from services.llm import llm_chat

        def _test():
            return llm_chat(
                [{"role": "user", "content": "Say 'JobHunter3000 connected!' and nothing else."}],
                settings,
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _test)
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
    import asyncio
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
    content_text = resume["content_text"]
    conn.close()

    def _do_analysis():
        analysis = analyze_resume(content_text, settings)
        analysis_conn = get_db()
        try:
            update_resume_analysis(analysis_conn, resume_id, analysis)
        finally:
            analysis_conn.close()
        return analysis

    try:
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, _do_analysis)
        return JSONResponse({"ok": True, "analysis": analysis})
    except Exception as e:
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


def _run_analyze_all(force: bool = False, model_override: str = None):
    """Synchronous worker for analyze-all (runs in thread pool)."""
    from services.resumes import (
        get_resumes, analyze_resume,
        update_resume_analysis, synthesize_candidate_profile,
    )

    settings = load_settings()

    # Override model if specified
    if model_override:
        if settings.get("llm_provider") == "openrouter":
            settings["openrouter_model"] = model_override
        elif settings.get("llm_provider") == "google":
            settings["google_model"] = model_override
        elif settings.get("llm_provider") == "ollama":
            settings["ollama_model"] = model_override

    conn = get_db()
    resumes = get_resumes(conn)

    results = {"analyzed": 0, "skipped": 0, "errors": [], "model": model_override or "default"}

    for r in resumes:
        if r.get("analysis") and not force:
            results["skipped"] += 1
            continue

        if not r.get("content_text"):
            results["errors"].append(f"{r['original_name']}: no text content")
            continue

        try:
            analysis = analyze_resume(r["content_text"], settings)
            update_resume_analysis(conn, r["id"], analysis)
            results["analyzed"] += 1
        except Exception as e:
            results["errors"].append(f"{r['original_name']}: {str(e)}")

    # Synthesize the unified profile from all resumes
    try:
        profile = synthesize_candidate_profile(conn, settings)
        results["profile"] = profile
    except Exception as e:
        results["profile_error"] = str(e)

    conn.close()
    return results


@app.post("/api/resumes/analyze-all")
async def api_analyze_all_resumes(request: Request):
    """Analyze all unanalyzed resumes, then synthesize a candidate profile."""
    import asyncio
    from functools import partial

    # Parse optional JSON body for force/model override
    force = False
    model_override = None
    try:
        body = await request.json()
        force = body.get("force", False)
        model_override = body.get("model") or None
    except Exception:
        pass

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, partial(_run_analyze_all, force=force, model_override=model_override)
    )
    return JSONResponse(results)


@app.get("/api/profile")
async def api_get_profile():
    """Get the synthesized candidate profile."""
    from services.resumes import load_candidate_profile
    profile = load_candidate_profile()
    if not profile:
        return JSONResponse({"error": "No profile yet. Analyze resumes first."}, status_code=404)
    return JSONResponse(profile)


# ---------------------------------------------------------------------------
# OpenRouter Credits
# ---------------------------------------------------------------------------

@app.get("/api/openrouter/credits")
async def api_openrouter_credits():
    """Fetch remaining credits from OpenRouter."""
    import httpx
    settings = load_settings()
    key = settings.get("openrouter_api_key", "")
    if not key:
        return JSONResponse({"ok": False, "error": "No API key configured"})
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            total_credits = float(data.get("total_credits", 0))
            total_usage = float(data.get("total_usage", 0))
            remaining = total_credits - total_usage
            return JSONResponse({
                "ok": True,
                "total_credits": round(total_credits, 4),
                "total_usage": round(total_usage, 4),
                "remaining": round(remaining, 4),
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


# ---------------------------------------------------------------------------
# Ollama models API
# ---------------------------------------------------------------------------

@app.get("/api/ollama/models")
async def api_ollama_models():
    """Fetch available models from the Ollama endpoint."""
    import httpx
    settings = load_settings()
    endpoint = settings.get("ollama_endpoint", "http://localhost:11434")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{endpoint}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return JSONResponse({
                "ok": True,
                "models": [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)} for m in models],
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200], "models": []})


# ---------------------------------------------------------------------------
# Scraper / Scorer / Suggest APIs
# ---------------------------------------------------------------------------

@app.post("/api/scraper/run")
async def api_run_scraper():
    """Run a full scrape across all enabled search profiles."""
    import asyncio
    import httpx as _httpx
    from services.scraper import run_full_scrape

    settings = load_settings()

    # Snapshot credits before run
    credits_before = None
    or_key = settings.get("openrouter_api_key", "")
    if or_key:
        try:
            async with _httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {or_key}"},
                )
                d = resp.json().get("data", {})
                credits_before = float(d.get("total_credits", 0)) - float(d.get("total_usage", 0))
        except Exception:
            pass

    # Log the run start
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO scrape_runs (started_at, status) VALUES (datetime('now'), 'running')"
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()

    def _do_scrape():
        results = run_full_scrape(settings)

        # Score new jobs automatically
        scored = {"scored": 0, "errors": []}
        try:
            from services.scorer import score_jobs
            score_conn = get_db()
            scored = score_jobs(score_conn, settings)
            score_conn.close()
        except Exception as e:
            scored["errors"].append(str(e))

        # Send notifications for high-scoring new jobs
        notified = 0
        try:
            from services.notifier import notify_job_match
            notify_conn = get_db()
            # Get jobs scored above notify threshold that haven't been notified
            threshold = settings.get("notify_threshold", 60)
            rows = notify_conn.execute(
                "SELECT * FROM jobs WHERE score >= ? AND notified = 0",
                (threshold,),
            ).fetchall()
            for row in rows:
                job = dict(row)
                score_data = {
                    "score": job.get("score", 0),
                    "pros": json.loads(job.get("pros", "[]") or "[]"),
                    "cons": json.loads(job.get("cons", "[]") or "[]"),
                    "fit_summary": job.get("fit_summary", ""),
                }
                result = notify_job_match(job, score_data, settings)
                if result.get("ok"):
                    notify_conn.execute(
                        "UPDATE jobs SET notified = 1 WHERE id = ?", (job["id"],)
                    )
                    notify_conn.commit()
                    notified += 1
            notify_conn.close()
        except Exception as e:
            results.setdefault("errors", []).append(f"Notify error: {e}")

        # Update scrape run record
        update_conn = get_db()
        update_conn.execute(
            """UPDATE scrape_runs SET
               completed_at = datetime('now'),
               jobs_found = ?, jobs_new = ?, jobs_scored = ?,
               notifications_sent = ?, status = ?
               WHERE id = ?""",
            (
                results.get("jobs_found", 0),
                results.get("jobs_new", 0),
                scored.get("scored", 0),
                notified,
                "error" if results.get("errors") else "completed",
                run_id,
            ),
        )
        update_conn.commit()
        update_conn.close()

        results["scored"] = scored.get("scored", 0)
        results["notified"] = notified
        return results

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _do_scrape)

    # Snapshot credits after run and calculate cost
    if or_key and credits_before is not None:
        try:
            async with _httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {or_key}"},
                )
                d = resp.json().get("data", {})
                credits_after = float(d.get("total_credits", 0)) - float(d.get("total_usage", 0))
                results["credits_before"] = round(credits_before, 4)
                results["credits_after"] = round(credits_after, 4)
                results["run_cost"] = round(credits_before - credits_after, 4)
        except Exception:
            pass

    return JSONResponse(results)


@app.post("/api/jobs/score-all")
async def api_score_all_jobs(request: Request):
    """Score all unscored jobs against the candidate profile."""
    import asyncio
    from services.scorer import score_jobs

    force = False
    try:
        body = await request.json()
        force = body.get("force", False)
    except Exception:
        pass

    settings = load_settings()

    def _do_score():
        conn = get_db()
        results = score_jobs(conn, settings, force=force)
        conn.close()
        return results

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _do_score)
    return JSONResponse(results)


@app.post("/api/jobs/{job_id}/score")
async def api_score_single_job(job_id: int):
    """Score a single job."""
    import asyncio
    from services.scorer import score_jobs

    settings = load_settings()

    def _do_score():
        conn = get_db()
        results = score_jobs(conn, settings, job_ids=[job_id], force=True)
        conn.close()
        return results

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _do_score)
    return JSONResponse(results)


@app.post("/api/jobs/manual")
async def api_add_manual_job(request: Request):
    """Manually add a job (FlexJobs, company sites, referrals, etc.)."""
    import asyncio
    from services.db import upsert_job

    body = await request.json()

    title = body.get("title", "").strip()
    company = body.get("company", "").strip()
    if not title or not company:
        return JSONResponse({"error": "Title and company are required"}, status_code=400)

    job_data = {
        "title": title,
        "company": company,
        "location": body.get("location", ""),
        "salary_text": body.get("salary_text", ""),
        "url": body.get("url", ""),
        "source": body.get("source", "manual"),
        "description": body.get("description", ""),
        "status": "new",
        "scraped_at": __import__("datetime").datetime.now().isoformat(),
    }

    conn = get_db()
    job_id = upsert_job(conn, job_data)
    if job_id <= 0:
        conn.close()
        return JSONResponse({"error": "Job with this URL already exists"}, status_code=409)

    result = {"ok": True, "id": job_id, "title": title, "company": company}

    conn.close()

    # Auto-score if requested
    if body.get("auto_score", True):
        from services.scorer import score_jobs
        settings = load_settings()

        def _score():
            score_conn = get_db()
            try:
                return score_jobs(score_conn, settings, job_ids=[job_id], force=True)
            finally:
                score_conn.close()

        try:
            loop = asyncio.get_event_loop()
            score_result = await loop.run_in_executor(None, _score)

            # Fetch the scored job to return the score
            conn2 = get_db()
            scored_job = get_job(conn2, job_id)
            conn2.close()
            if scored_job:
                result["score"] = scored_job.get("score")
                result["fit_summary"] = scored_job.get("fit_summary")
        except Exception as e:
            result["score_error"] = str(e)

    return JSONResponse(result)


@app.post("/api/scraper/suggest")
async def api_suggest_searches():
    """Use AI to suggest search strategies based on candidate profile."""
    import asyncio
    from services.scorer import suggest_searches

    settings = load_settings()

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, suggest_searches, settings, None)
    return JSONResponse(results)


# ---------------------------------------------------------------------------
# Resume / Cover Letter Generation
# ---------------------------------------------------------------------------

@app.post("/api/jobs/{job_id}/generate-resume")
async def api_generate_resume(job_id: int):
    """Generate a tailored resume for a job posting."""
    import asyncio
    from services.generator import generate_resume

    conn = get_db()
    job = get_job(conn, job_id)
    conn.close()
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    settings = load_settings()

    def _gen():
        return generate_resume(job, settings)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _gen)

    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/jobs/{job_id}/generate-cover-letter")
async def api_generate_cover_letter(job_id: int):
    """Generate a tailored cover letter for a job posting."""
    import asyncio
    from services.generator import generate_cover_letter

    conn = get_db()
    job = get_job(conn, job_id)
    conn.close()
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    settings = load_settings()

    def _gen():
        return generate_cover_letter(job, settings)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _gen)

    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.get("/api/jobs/{job_id}/download/{doc_type}")
async def api_download_doc(job_id: int, doc_type: str):
    """Download a generated resume or cover letter as .docx."""
    if doc_type not in ("resume", "cover"):
        return JSONResponse({"error": "Invalid doc type"}, status_code=400)

    conn = get_db()
    job = get_job(conn, job_id)
    conn.close()
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    field = "resume_path" if doc_type == "resume" else "cover_letter_path"
    path = job.get(field)
    if not path or not os.path.exists(path):
        return JSONResponse({"error": f"No {doc_type} generated yet"}, status_code=404)

    # Build a nice filename: John_Burks_Resume_CompanyName.docx
    company = (job.get("company") or "Unknown").replace(" ", "_")[:30]
    if doc_type == "resume":
        download_name = f"John_Burks_Resume_{company}.docx"
    else:
        download_name = f"John_Burks_CoverLetter_{company}.docx"

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=download_name,
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
