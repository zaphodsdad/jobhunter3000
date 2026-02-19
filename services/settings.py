"""
Settings management — load/save from data/settings.json.
"""

import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "settings.json")

DEFAULTS = {
    "llm_provider": "openrouter",       # "openrouter" or "ollama"
    "openrouter_api_key": "",
    "openrouter_model": "anthropic/claude-sonnet-4",
    "ollama_endpoint": "http://localhost:11434",
    "ollama_model": "qwen2.5-coder:32b",
    "pushover_user_key": "",
    "pushover_api_token": "",
    "notify_threshold": 60,
    "priority_threshold": 80,
    "scrape_interval_hours": 8,
    "search_profiles": [
        {
            "name": "Operations Manager OKC",
            "boards": ["indeed", "simplyhired"],
            "query": "operations manager",
            "location": "Oklahoma City, OK",
            "radius_miles": 30,
            "salary_min": 50000,
            "enabled": True,
        },
        {
            "name": "Building/Facility Manager",
            "boards": ["indeed", "simplyhired"],
            "query": "building manager OR facility manager",
            "location": "Oklahoma City, OK",
            "radius_miles": 45,
            "salary_min": 50000,
            "enabled": True,
        },
        {
            "name": "IT Infrastructure OKC",
            "boards": ["indeed", "simplyhired"],
            "query": "IT infrastructure OR desktop support OR systems administrator",
            "location": "Oklahoma City, OK",
            "radius_miles": 30,
            "salary_min": 50000,
            "enabled": True,
        },
        {
            "name": "Oil & Gas Operations",
            "boards": ["indeed", "simplyhired"],
            "query": "field operations OR operations coordinator OR MWD",
            "location": "Oklahoma",
            "radius_miles": 60,
            "salary_min": 55000,
            "enabled": True,
        },
        {
            "name": "Data Center Operations",
            "boards": ["indeed", "simplyhired"],
            "query": "data center operations OR NOC",
            "location": "Oklahoma City, OK",
            "radius_miles": 45,
            "salary_min": 50000,
            "enabled": True,
        },
    ],
    "exclude_keywords": [
        "security clearance required",
        "commission only",
        "CDL required",
    ],
    "max_days_old": 14,
}


def load_settings() -> dict:
    """Load settings from JSON file, filling in defaults for missing keys."""
    settings = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            stored = json.load(f)
        settings.update(stored)
    return settings


def save_settings(data: dict) -> dict:
    """Save settings to JSON file. Returns the saved settings."""
    current = load_settings()
    to_save = {}
    for key in DEFAULTS:
        if key in data:
            val = data[key]
            # Coerce types to match defaults
            if isinstance(DEFAULTS[key], int) and isinstance(val, str):
                try:
                    val = int(val)
                except ValueError:
                    val = DEFAULTS[key]
            to_save[key] = val
        elif key in current:
            to_save[key] = current[key]
        else:
            to_save[key] = DEFAULTS[key]
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(to_save, f, indent=2)
    return to_save
