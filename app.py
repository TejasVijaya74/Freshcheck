"""Stale-Answer Detector: Bifrost (LLM gateway) + Tavily (live web search)."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
BIFROST_URL = os.getenv("BIFROST_URL", "http://localhost:8080/v1/chat/completions")
MODEL = os.getenv("BIFROST_MODEL", "openai/gpt-4o-mini")
BIFROST_KEY = os.getenv("BIFROST_API_KEY", "")

app = FastAPI(title="Stale-Answer Detector")


def llm(system: str, user: str) -> dict:
    """All model calls go through Bifrost so models/providers are swappable via config."""
    headers = {"Content-Type": "application/json"}
    if BIFROST_KEY:
        headers["Authorization"] = f"Bearer {BIFROST_KEY}"
    r = requests.post(BIFROST_URL, headers=headers, timeout=90, json={
        "model": MODEL, "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    })
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)  # tolerate code fences / preamble
    return json.loads(m.group(0))


def tavily(query: str) -> list[dict]:
    """Live web retrieval through Tavily."""
    r = requests.post("https://api.tavily.com/search", timeout=60,
                      headers={"Authorization": f"Bearer {TAVILY_KEY}"},
                      json={"query": query, "search_depth": "advanced", "max_results": 5,
                            "include_raw_content": False})
    r.raise_for_status()
    return [{"title": x.get("title"), "url": x["url"], "content": (x.get("content") or "")[:900],
             "published": x.get("published_date")} for x in r.json().get("results", [])]


EXTRACT_SYS = """You extract factual claims from an AI-generated answer and decide which are time-sensitive.
Return ONLY JSON: {"claims":[{"claim":str,"category":"pricing|api_version|law_regulation|leadership|product_release|statistics|other",
"time_sensitive":bool,"staleness_risk":"low|medium|high","search_query":str}]}
Time-sensitive = could plausibly have changed (prices, versions, laws, office holders, 'latest/current' statements, rankings, availability).
Timeless facts (history, math, definitions) are time_sensitive=false. search_query must be a short, self-contained web query."""

JUDGE_SYS = """You verify one claim against web evidence. Today's date is {today}.
Return ONLY JSON: {{"verdict":"current|outdated|partially_outdated|unverifiable",
"freshness_score":int 0-100,"confidence":"low|medium|high","explanation":str,
"current_info":str|null,"evidence_urls":[str]}}
Scoring: 90-100 confirmed accurate by recent sources; 60-89 mostly accurate / minor drift; 30-59 partially outdated or weak evidence;
0-29 contradicted by current sources. Use ONLY the evidence given; if it is insufficient, use 'unverifiable' and score 35-50."""


class Req(BaseModel):
    answer: str


def verify(c: dict) -> dict:
    try:
        ev = tavily(c["search_query"])
        j = llm(JUDGE_SYS.format(today=date.today().isoformat()),
                f"CLAIM: {c['claim']}\n\nEVIDENCE:\n" + json.dumps(ev, indent=1))
        j["freshness_score"] = max(0, min(100, int(j.get("freshness_score", 40))))
        return {**c, **j, "sources": ev}
    except Exception as e:  # keep one failure from sinking the whole report
        return {**c, "verdict": "unverifiable", "freshness_score": None,
                "explanation": f"Verification failed: {e}", "sources": []}


@app.post("/api/check")
def check(req: Req):
    if not TAVILY_KEY:
        raise HTTPException(500, "TAVILY_API_KEY is not set")
    if len(req.answer) > 8000:
        raise HTTPException(400, "Answer too long (max 8000 chars)")
    try:
        claims = llm(EXTRACT_SYS, req.answer)["claims"]
    except Exception as e:
        raise HTTPException(502, f"Bifrost request failed: {e}")
    flagged = [c for c in claims if c.get("time_sensitive")]
    with ThreadPoolExecutor(max_workers=5) as ex:
        checked = list(ex.map(verify, flagged))
    skipped = [c for c in claims if not c.get("time_sensitive")]
    scores = [c["freshness_score"] for c in checked if c["freshness_score"] is not None]
    return {"overall_score": round(sum(scores) / len(scores)) if scores else None,
            "checked": checked, "timeless": skipped}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
