# Stale-Answer Detector

Paste an LLM answer → get time-sensitive claims, live re-verification, and a 0–100 freshness score per claim.

## Pipeline
1. **Claim identification** – Bifrost → LLM extracts atomic claims, tags category + staleness risk.
2. **Freshness detection** – only time-sensitive claims (pricing, versions, laws, leadership…) are flagged.
3. **Live verification** – Tavily searches the web for each flagged claim (in parallel).
4. **Freshness scoring** – Bifrost → LLM judges claim vs. evidence, returns verdict, score, correction, sources.

**Where each tech is used:** Tavily = live retrieval (`tavily()`); Bifrost = every model call (`llm()`), so you can swap models/providers or add fallbacks, budgets and logging purely in gateway config.

## Run
```bash
# 1. Start Bifrost gateway (https://github.com/maximhq/bifrost) and add a provider key via its UI at localhost:8080
npx -y @maximhq/bifrost
# 2. Run the app
pip install -r requirements.txt
cp .env.example .env   # add TAVILY_API_KEY
uvicorn app:app --reload   # open http://localhost:8000
```
Adjust `BIFROST_MODEL` (format `provider/model`) to whatever you configured.
