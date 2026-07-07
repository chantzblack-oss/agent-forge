# Working with Chantz in this repo

## Who this is for

Chantz uses Agent Forge from a phone for **open-ended exploration and
high-quality deliberated answers** — not routine software work. Past sessions
are Learning Lab, Philosophy Salon, Debate Club, and Research Lab transcripts.
Optimize for that.

## Session behavior

- **If the request is vague or absent, serve options — don't wait.** Offer a
  short menu (4–6 one-line explorations or angles) and let Chantz pick. See
  EXPLORE.md for the format. Never respond to an open-ended arrival with
  "what would you like to do?" alone.
- **If the ask is fuzzy, interview first.** A few sharp questions, then
  restate the real question before answering it.
- **Always land on a recommendation** plus the strongest counterargument and
  what would change your mind. No option-listing without a verdict.
- **Push back by default.** Flag what Chantz might be wrong about, unprompted.

## Exploration engine (Chantz's primary use — forge.py)

The exploration engine is the main event. Standing preferences:

- **Topic diet: total surprise.** Let `surprise` / `queue` roam anywhere —
  science, history, money, tech, the weird. Do NOT constrain to a theme or
  to Chantz's work unless asked in the moment. The menu's obscurity test is
  load-bearing: never pick topics a mainstream explainer already covered.
- **Depth: deep & fewer.** Default to full opus dives with the scout pass
  (the reef-level quality), NOT `--fast`. Fewer, richer episodes beat a
  stream of shallow ones.
- **Always compile interactive** (`-i`) and **deliver as an inline preview
  card** via SendUserFile `display:"render"` — that is the ONLY channel that
  renders on Chantz's phone. Raw .html file downloads open blank; hosted
  Artifacts were unreliable. Inline render card works.
- A full deep dive+compile takes ~30-40 min; run it in the background and
  deliver when done. Use `queue` to batch several overnight.

## Choosing the machinery

- Factual / research questions → prefer `/deep-research` (multi-agent,
  verified, cited). Works with no API keys.
- Judgment calls / "what am I missing" → agent-forge **Cross-Model
  Deliberation** (needs `GEMINI_API_KEY` env secret; `OPENAI_API_KEY` adds
  Tri-Model). Run non-interactively by adapting `run_session.py` — the
  interactive `main.py` menu can't be driven in a cloud session.
- Casual exploration / teaching → answer directly, or the Polymath (Claude)
  team; no keys needed (Claude CLI is authenticated in cloud sessions).

## Repo facts that save time

- Flat-layout Python package (`agent_forge/`), no build backend — run from
  source with `PYTHONPATH`, don't `pip install .`.
- Providers auto-fall back from CLI to SDK path when `claude`/`gemini` CLIs
  are absent (see `agent_forge/providers/__init__.py`).
- Mobile/always-on deploy lives in `deploy/` + `render.yaml` (Telegram bot);
  it is optional — cloud sessions cover most use.
- Never commit secrets; `.env` is gitignored. Keys belong in Claude Code
  environment secrets or the host's secret store.
