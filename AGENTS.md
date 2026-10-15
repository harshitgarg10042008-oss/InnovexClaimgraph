# Agent Working Rules

- Work directly on main. No other branches.
- Do only the task given. No extra features or refactors outside it.
- Never edit ground-truth files (data/synthetic/**/*.truth.json, expected*.json) to make a test or metric pass. If one looks wrong, show the evidence and ask.
- Never fabricate data, cache entries or test output. If a real call cannot be made, say so.
- Paste raw command output as evidence, not summaries.
- Never print, log or commit LLM_API_KEY or any secret. .env stays untracked.
- Do not git push or move tags unless the task says so.
- If something fails twice, stop and report. Do not loop.
- backend/app/rules is pure and deterministic: no DB, no network, no LLM, no today().
- Frontend design: no purple, indigo or violet, no gradients, no glow, no emoji, flat 1px rules, tokens from master plan section 8.
