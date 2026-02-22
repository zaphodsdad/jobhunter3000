"""
Job scoring — LLM rates jobs 0-100 against the candidate profile and search preferences.
"""

import json
from services.llm import llm_chat
from services.resumes import load_candidate_profile
from services.settings import load_settings


def _scoring_settings(settings: dict) -> dict:
    """Build a settings dict that routes LLM calls through the scoring model."""
    s = dict(settings)
    scoring_provider = s.get("scoring_provider", "")
    scoring_model = s.get("scoring_model", "")
    if scoring_provider:
        s["llm_provider"] = scoring_provider
    if scoring_model:
        # Set the model for whichever provider we're using
        provider = s.get("llm_provider", "openrouter")
        if provider == "openrouter":
            s["openrouter_model"] = scoring_model
        elif provider == "google":
            s["google_model"] = scoring_model
        elif provider == "ollama":
            s["ollama_model"] = scoring_model
    return s


def parse_job_posting_text(raw_text: str, url: str, settings: dict) -> dict:
    """Use LLM to extract structured job fields from raw page text.

    Used by the browser extension when site-specific extractors fail
    and we only have raw body text.
    """
    # Truncate to avoid blowing up context
    truncated = raw_text[:8000]

    prompt = f"""Extract job posting details from this page text. The page URL is: {url}

PAGE TEXT:
{truncated}

Return ONLY valid JSON (no markdown fences):
{{"title": "Job Title", "company": "Company Name", "location": "City, State or Remote", "salary_text": "salary range if mentioned or empty string", "description": "the job description text (key responsibilities, requirements, qualifications — up to 2000 chars)"}}

If you cannot identify a job posting in this text, return:
{{"error": "Could not identify a job posting on this page"}}"""

    score_settings = _scoring_settings(settings)
    result = llm_chat(
        [{"role": "user", "content": prompt}],
        score_settings,
    )

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return {"error": "Failed to parse LLM response"}


def score_job(job: dict, settings: dict, profile: dict = None) -> dict:
    """Score a single job against the candidate profile. Returns score dict."""
    if not profile:
        profile = load_candidate_profile()

    if not profile:
        return {"score": 0, "pros": [], "cons": ["No candidate profile available"], "fit_summary": "Cannot score without a candidate profile."}

    # Quick dealbreaker check (keyword match, no LLM needed)
    dealbreakers = settings.get("candidate_dealbreakers", [])
    job_text = f"{job.get('title', '')} {job.get('description', '')} {job.get('company', '')}".lower()
    for db in dealbreakers:
        if db.lower() in job_text:
            return {
                "score": 0,
                "pros": [],
                "cons": [f"Dealbreaker: contains '{db}'"],
                "fit_summary": f"Auto-rejected: job contains dealbreaker keyword '{db}'.",
            }

    # Build the scoring prompt
    prefs = {
        "location": settings.get("candidate_location", ""),
        "radius_miles": settings.get("candidate_radius_miles", 30),
        "salary_min": settings.get("candidate_salary_min", 0),
        "salary_max": settings.get("candidate_salary_max", 0),
        "work_mode": settings.get("candidate_work_mode", "any"),
        "target_roles": settings.get("candidate_target_roles", []),
        "target_industries": settings.get("candidate_target_industries", []),
        "nice_to_haves": settings.get("candidate_nice_to_haves", []),
        "willing_to_travel": settings.get("candidate_willing_to_travel", 10),
    }

    job_info = (
        f"Title: {job.get('title', 'Unknown')}\n"
        f"Company: {job.get('company', 'Unknown')}\n"
        f"Location: {job.get('location', 'Unknown')}\n"
        f"Industry: {job.get('industry', 'Unknown')}\n"
        f"Salary: {job.get('salary_text', 'Not listed')}\n"
        f"Source: {job.get('source', 'Unknown')}\n"
        f"Description:\n{(job.get('description', '') or '')[:3000]}"
    )

    prompt = f"""You are a job match analyst. Score how well this job matches the candidate on a scale of 0-100.

CANDIDATE PROFILE:
Name: {profile.get('name', 'Unknown')}
Headline: {profile.get('headline', '')}
Experience: {profile.get('experience_years', 0)}+ years, {profile.get('experience_level', 'unknown')} level
Core Strengths: {', '.join(profile.get('core_strengths', []))}
Skills: {', '.join(profile.get('all_skills', [])[:20])}
Industries: {', '.join(profile.get('industries', []))}
Target Roles: {', '.join(profile.get('target_roles', []))}
Unique Value: {profile.get('unique_value', '')}
{f"Technical Projects/Homelab: {settings.get('candidate_technical_projects', '')}" if settings.get('candidate_technical_projects') else ''}

SEARCH PREFERENCES:
Preferred Location: {prefs['location']} (within {prefs['radius_miles']} miles)
Salary Range: ${prefs['salary_min']:,} - ${prefs['salary_max']:,}{' (flexible on upper)' if prefs['salary_max'] == 0 else ''}
Work Mode: {prefs['work_mode']}
Target Roles: {', '.join(prefs['target_roles']) if prefs['target_roles'] else 'See candidate profile'}
Target Industries: {', '.join(prefs['target_industries']) if prefs['target_industries'] else 'See candidate profile'}
Nice-to-Haves: {', '.join(prefs['nice_to_haves']) if prefs['nice_to_haves'] else 'None specified'}
Max Travel: {prefs['willing_to_travel']}%

JOB POSTING:
{job_info}

SCORING GUIDE:
- 90-100: Perfect match — right role, right location, right pay, strong skill overlap
- 70-89: Strong match — most criteria met, worth applying
- 50-69: Moderate match — some fit, might be a stretch or compromise
- 30-49: Weak match — significant gaps or misalignment
- 0-29: Poor match — wrong field, wrong location, or doesn't fit at all

CRITICAL RULES (override the scale above):
- If the job requires a specific professional license the candidate does NOT have (pharmacist, nurse, RN, LPN, CPA, PE, attorney, CDL, etc.), score 0-10 regardless of other factors.
- If the job is in a completely unrelated field (healthcare clinical, legal, accounting, teaching K-12, pure software engineering), score 0-20.
- If the job title is clearly a different profession (pharmacist, therapist, dental hygienist, sales representative, financial analyst, radiologist, etc.), score 0-15.
- "Operations" in a job title does NOT automatically make it a match. Pharmacy Operations Manager or Clinical Operations Manager are healthcare roles, NOT operations management roles this candidate qualifies for.
- Only score above 60 if the candidate could genuinely perform this job with their actual experience.
- Be skeptical. When in doubt, score lower. A false positive wastes the candidate's time.

ALSO PROVIDE:
- "summary": A 2-sentence summary of the role (what the job actually is and what you'd be doing). Write for a job seeker scanning 50 listings — be specific, not generic.
- "ghost_risk": Assess if this might be a ghost/fake job. Return "low", "medium", or "high".
  - "high": Very vague description (no specific skills/tools/responsibilities listed), generic corporate boilerplate, no salary info AND no specific team/department mentioned
  - "medium": Some vague elements but has at least some concrete requirements
  - "low": Specific requirements, tools, team, responsibilities clearly listed
- "keyword_match": Extract the top 10-12 most important required skills/tools/qualifications from the JD. For each, check if the candidate's resume/profile contains a match. Return as array of objects:
  [{{"keyword": "skill name", "category": "hard_skill"|"soft_skill"|"tool"|"certification", "matched": true|false}}]
- "gaps": List 3-5 specific gaps between the candidate and this role. For each, note if they have a transferable skill that partially covers it:
  [{{"gap": "what they need", "transferable": "what you have that partially covers it (or empty string if nothing)"}}, ...]
- "salary_estimate": If the job posting does NOT list a specific salary/range, estimate the likely annual salary range based on the job title, location, company, and industry. Return as a string like "$65,000 - $85,000" or null if salary IS listed in the posting.

Return ONLY valid JSON (no markdown fences):
{{"score": 0, "pros": ["pro 1", "pro 2", "pro 3"], "cons": ["con 1", "con 2"], "fit_summary": "One sentence.", "summary": "Two sentences.", "ghost_risk": "low", "keyword_match": [{{"keyword": "Project Management", "category": "hard_skill", "matched": true}}], "gaps": [{{"gap": "PMP certification", "transferable": "20 years of project coordination experience"}}], "salary_estimate": "$65,000 - $85,000"}}"""

    # Use the scoring-specific model (cheaper/faster than the analysis model)
    score_settings = _scoring_settings(settings)

    result = llm_chat(
        [{"role": "user", "content": prompt}],
        score_settings,
    )

    # Parse JSON
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        data = json.loads(cleaned)
        # Ensure score is int 0-100
        data["score"] = max(0, min(100, int(data.get("score", 0))))
        return data
    except (json.JSONDecodeError, ValueError):
        return {
            "score": 0,
            "pros": [],
            "cons": ["Failed to parse scoring response"],
            "fit_summary": result[:200],
        }


def score_jobs(conn, settings: dict = None, job_ids: list = None, force: bool = False) -> dict:
    """Score multiple jobs. Returns summary of results."""
    if not settings:
        settings = load_settings()

    profile = load_candidate_profile()
    if not profile:
        return {"error": "No candidate profile. Analyze resumes first.", "scored": 0}

    # Get jobs to score
    if job_ids:
        placeholders = ",".join("?" * len(job_ids))
        rows = conn.execute(f"SELECT * FROM jobs WHERE id IN ({placeholders})", job_ids).fetchall()
    elif force:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM jobs WHERE score IS NULL ORDER BY id").fetchall()

    jobs = [dict(r) for r in rows]
    results = {"scored": 0, "skipped": 0, "errors": []}

    for job in jobs:
        if job.get("score") is not None and not force:
            results["skipped"] += 1
            continue

        try:
            score_data = score_job(job, settings, profile)
            conn.execute(
                """UPDATE jobs SET score = ?, pros = ?, cons = ?, fit_summary = ?,
                   score_details = ?, summary = ?, ghost_risk = ?, keyword_match = ?,
                   salary_estimate = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    score_data["score"],
                    json.dumps(score_data.get("pros", [])),
                    json.dumps(score_data.get("cons", [])),
                    score_data.get("fit_summary", ""),
                    json.dumps(score_data),
                    score_data.get("summary", ""),
                    score_data.get("ghost_risk", ""),
                    json.dumps(score_data.get("keyword_match", [])),
                    score_data.get("salary_estimate"),
                    job["id"],
                ),
            )
            conn.commit()
            results["scored"] += 1
        except Exception as e:
            results["errors"].append(f"Job {job['id']} ({job.get('title', '?')}): {str(e)}")

    return results


def generate_interview_prep(job: dict, settings: dict = None, profile: dict = None) -> dict:
    """Generate interview preparation questions and talking points for a job."""
    if not settings:
        settings = load_settings()
    if not profile:
        profile = load_candidate_profile()

    if not profile:
        return {"error": "No candidate profile. Analyze resumes first."}

    job_info = (
        f"Title: {job.get('title', 'Unknown')}\n"
        f"Company: {job.get('company', 'Unknown')}\n"
        f"Location: {job.get('location', 'Unknown')}\n"
        f"Description:\n{(job.get('description', '') or '')[:3000]}"
    )

    prompt = f"""You are an expert interview coach. Generate interview preparation materials for this specific job.

CANDIDATE:
{profile.get('name', 'Unknown')} — {profile.get('headline', '')}
{profile.get('experience_years', 0)}+ years experience
Core Strengths: {', '.join(profile.get('core_strengths', []))}
Skills: {', '.join(profile.get('all_skills', [])[:20])}

Work History:
{chr(10).join(f"- {j['title']} @ {j['company']} ({j['duration']})" for j in profile.get('work_history', [])[:5])}

JOB:
{job_info}

Generate:
1. 5 behavioral questions they're likely to ask (with a suggested talking point from the candidate's experience for each)
2. 5 technical/role-specific questions (with suggested answers based on the candidate's background)
3. 3 situational questions (with STAR-method response outlines)
4. 5 smart questions the candidate should ASK the interviewer (including "What would be the most challenging aspect of this role for someone new?" — this technique scored huge engagement with hiring managers)

Return ONLY valid JSON (no markdown fences):
{{
    "behavioral": [
        {{"question": "...", "talking_point": "Draw on your experience with..."}}
    ],
    "technical": [
        {{"question": "...", "suggested_answer": "..."}}
    ],
    "situational": [
        {{"question": "...", "star_outline": "Situation: ... Task: ... Action: ... Result: ..."}}
    ],
    "questions_to_ask": [
        {{"question": "...", "why": "Shows you're thinking about..."}}
    ]
}}"""

    result = llm_chat(
        [{"role": "user", "content": prompt}],
        settings,
    )

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "Failed to parse interview prep", "raw": result[:500]}


def suggest_searches(settings: dict = None, profile: dict = None) -> dict:
    """Use AI to suggest search queries and target companies based on candidate profile."""
    if not settings:
        settings = load_settings()
    if not profile:
        profile = load_candidate_profile()

    if not profile:
        return {"error": "No candidate profile. Analyze resumes first."}

    prefs = {
        "location": settings.get("candidate_location", ""),
        "target_roles": settings.get("candidate_target_roles", []),
        "target_industries": settings.get("candidate_target_industries", []),
        "salary_min": settings.get("candidate_salary_min", 0),
    }

    prompt = f"""You are a career strategist and job search expert. Based on this candidate's profile and preferences, suggest search strategies they HAVEN'T thought of.

CANDIDATE:
{profile.get('name', 'Unknown')} — {profile.get('headline', '')}
{profile.get('experience_years', 0)}+ years experience
Skills: {', '.join(profile.get('all_skills', [])[:25])}
Industries: {', '.join(profile.get('industries', []))}
Current Target Roles: {', '.join(prefs['target_roles']) if prefs['target_roles'] else ', '.join(profile.get('target_roles', []))}
Location: {prefs['location']}
Salary Target: ${prefs['salary_min']:,}+

Work History:
{chr(10).join(f"- {j['title']} @ {j['company']} ({j['duration']})" for j in profile.get('work_history', []))}

Unique Value: {profile.get('unique_value', '')}

Think creatively. This person has transferable skills they may not realize are valuable. Consider:
- Companies in their area that need their specific mix of skills
- Industries they haven't considered that value ops/facility/technical experience
- Job title variations they might not be searching for
- Niche roles that combine their unusual skill set (ops + tech + CNC + e-commerce)

Return ONLY valid JSON (no markdown fences):
{{
    "suggested_searches": [
        {{"query": "search query text", "reason": "why this would find good matches"}},
        {{"query": "another query", "reason": "why"}}
    ],
    "target_companies": [
        {{"name": "Company Name", "reason": "why they'd be a good fit", "likely_roles": ["role 1"]}}
    ],
    "unexpected_industries": [
        {{"industry": "Industry Name", "reason": "why their skills transfer here"}}
    ],
    "title_variations": ["Job Title 1", "Job Title 2"],
    "strategy_notes": "1-2 sentences of overall search strategy advice"
}}"""

    result = llm_chat(
        [{"role": "user", "content": prompt}],
        settings,
    )

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "Failed to parse suggestions", "raw": result[:500]}
