"""
Pushover notification service — sends job match alerts to phone.
"""

import json
import requests


def send_notification(title: str, message: str, settings: dict,
                      url: str = None, priority: int = 0) -> dict:
    """Send a Pushover notification. Returns response dict."""
    token = settings.get("pushover_api_token", "")
    user = settings.get("pushover_user_key", "")

    if not token or not user:
        return {"ok": False, "error": "Pushover credentials not configured"}

    data = {
        "token": token,
        "user": user,
        "title": title,
        "message": message,
        "priority": priority,
    }

    if url:
        data["url"] = url
        data["url_title"] = "View Job Posting"

    try:
        resp = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
        if resp.status_code == 200:
            return {"ok": True}
        else:
            return {"ok": False, "error": resp.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def notify_job_match(job: dict, score_data: dict, settings: dict) -> dict:
    """Send a notification for a high-scoring job match."""
    score = score_data.get("score", 0)
    notify_threshold = settings.get("notify_threshold", 60)
    priority_threshold = settings.get("priority_threshold", 80)

    if score < notify_threshold:
        return {"ok": False, "reason": "below_threshold"}

    priority = 1 if score >= priority_threshold else 0

    pros = score_data.get("pros", [])
    cons = score_data.get("cons", [])
    fit = score_data.get("fit_summary", "")

    lines = [
        f"{job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}",
        f"{job.get('location', '')} | {job.get('salary_text', 'Salary not listed')}",
        "",
    ]

    if pros:
        lines.append("Pros: " + "; ".join(pros[:3]))
    if cons:
        lines.append("Cons: " + "; ".join(cons[:2]))
    if fit:
        lines.append("")
        lines.append(fit)

    title = f"JobHunter3000: {score}/100"
    message = "\n".join(lines)
    url = job.get("url", "")

    return send_notification(title, message, settings, url=url, priority=priority)
