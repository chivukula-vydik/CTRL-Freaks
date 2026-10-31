# AGENTS.md: Git and Versioning Rules

Every AI agent in this repo (Claude Code, Cursor, Copilot, Codex, Windsurf) follows these rules. If a rule blocks you, stop and ask your human. Do not work around it. Code rules are in CLAUDE.md; the day-of runbook is INTEGRATION.md.

## 0. Commands

```
INSTALL: pip install -r requirements-dev.txt
TEST:    pytest -q                                  (needs `docker compose up -d db`)
EVAL:    python eval/run_eval.py --label <x>
RUN:     uvicorn app.main:app --reload   |   API_URL=http://localhost:8000 streamlit run ui/app.py
```

## 1. Branch model: main + short feature branches + tags

- `main` is the only long-lived branch. It must always pass `pytest -q`. Nobody commits to it directly; the integrator (P5) merges PRs.
- Work happens on short branches off the latest `main`: `<type>/<owner>-<desc>`, e.g. `feat/vydik-refund-tool`, `fix/ravi-ui-header`, `data/satvik-eval-set`. Types: `feat fix data test docs chore hotfix`.
- One branch = one task. Merge within ~60 minutes of starting it. Delete after merge.
- Exception: during bootstrap (section 3) only `bootstrap/v0.1.0` may touch the shared files.

## 2. File ownership (no claims file; ownership is fixed by role)

| Role | Owns | Shared hotspot rule |
|---|---|---|
| P3 AI core | `app/domain/<name>.py` tools, intents, PLAN | only P3 edits tools; others send snippets |
| P2 Backend | SCHEMA + VALIDATIONS block in the domain file, `app/schemas.py`, `app/main.py` contract diffs | SCHEMA changes go in their own small PR, merged first |
| P4 Data/eval | `data/<name>/**` (docs, register, csv, rule_registry, eval_set) | new files only; never edit `app/` |
| P1 Frontend | `ui/app.py`, demo script | none |
| P5 Integrator | merges, `.env.example`, README, tags, frozen core (`app/` minus domain file) | frozen core changes need P5's OK |

Do not edit files owned by another role. If you must, ask that person first and keep the change in its own commit.

## 3. Bootstrap: skeleton to v0.1.0 (T0 = problem statement handed out)

- T0 to T0+20m: nobody commits. Read the doc, fill the mapping table in INTEGRATION.md section 0.
- T0+20m: P5 creates `bootstrap/v0.1.0` from `main`, runs `python scripts/new_domain.py <name>`, pushes.
- On `bootstrap/v0.1.0` only (P5 + P3, with P2 pasting SCHEMA): domain file TODO 1 to 7 minimum, `.env.example` (DOMAIN, SUBJECT_HEADER), contract diffs.
- In parallel, on their own branches, touching only their own new files: P4 `data/<name>/` (1 doc + register row first, then the rest), P1 `ui/app.py` labels.
- v0.1.0 gate. ALL must be true before tagging:
  1. `pytest -q` green
  2. `python scripts/load_data.py` loads the pack with 0 validation violations
  3. `/ask` returns a cited `retrieved_fact` for a question from a real doc
  4. `/ask` returns a `calculated` answer from one tool using one `ctx.rule()` value
  5. another user's record gives `refused`; an off-topic question gives `not_found`
  6. `/health` shows database, vector store and LLM ok on the live stack
- Then P5 merges bootstrap into `main` (P4 and P1 branches right after), tags `v0.1.0`, and posts "rebase now". From here section 1 applies to everyone.
- Target: v0.1.0 by T0+75m. If the gate is not met by T0+90m, cut scope (one intent, one tool), do not wait.

## 4. Before starting a task

```bash
git switch main && git pull --ff-only
git switch -c <type>/<owner>-<desc>
```

## 5. Commits

```
<type>(<scope>): <imperative summary, max 72 chars>

Agent: <tool-name>
```

- Small and atomic; every commit runs. No `WIP` on `main`.
- Never commit `.env`, keys, tokens, judge data you were told not to share, `__pycache__`, `eval/reports/*.json`, files over 5 MB, or generated folders (`graphify-out/` etc.).
- Line endings are LF (`.gitattributes`). Never reformat or re-save files you did not change.

## 6. Pre-push checklist

1. `git fetch origin && git rebase origin/main`. Resolve conflicts properly; never drop someone else's change. If the conflict is in a file you don't own, stop and ask.
2. `pytest -q` passes.
3. If you touched `app/` or `data/<name>/`: run EVAL and put the numbers in the PR.
4. `git diff origin/main --stat` shows only files your task needed. Line-ending-only diffs = stop and fix.
5. Secret check: `git diff origin/main | grep -iE "api[_-]?key|secret|token|password|PRIVATE KEY"` returns nothing real.

Then `git push -u origin <branch>` and open a PR to `main`.

## 7. Pull requests

- Title in commit format. Body: what, why, how tested, eval numbers if relevant, known gaps.
- Squash merge, by P5 only. Agents never merge.
- Red tests on `main`: whoever broke it fixes or reverts within 15 minutes.

## 8. Versioning

`vMAJOR.MINOR.PATCH`, `0.x` until submission. Release notes go in the annotated tag message (no CHANGELOG file: it conflicts on every PR).

| Tag | Meaning |
|---|---|
| `v0.0.0` | skeleton, before the problem statement |
| `v0.1.0` | gate in section 3 met: first end-to-end cited answer + one tool |
| `v0.2.0` | every question type in the doc answers correctly on the eval |
| `v0.3.0` | actions, refusals, injection, conflicts covered; eval on the real model |
| `v0.4.0` | deployed URL + UI + README; demo rehearsed |
| `v0.x.y` | PATCH: a fix on top of a tagged milestone |
| `v1.0.0` | final submission |

```bash
git switch main && git pull --ff-only
git tag -a v0.2.0 -m "v0.2.0: all question types; eval correctness 0.xx"
git push origin v0.2.0
```

- Only P5 tags. Never move or delete a tag. Tag every build that is demoed or judged.

## 9. Forbidden without explicit human approval

- `git push --force` on `main`; on your own branch only `--force-with-lease`.
- `git reset --hard`, `git clean -fd`, `git checkout -- .`, `git stash drop` on work you did not create.
- Rewriting pushed history on `main`. Merging into `main`. Deleting others' branches or tags.
- Editing `.gitignore`, `.gitattributes`, CI, repo settings, `requirements*.txt`.
- Disabling, skipping or deleting tests to get green.
- Deleting, renaming or reformatting files outside your task.

## 10. Deadline rules (TD = submission time)

- TD-2h: feature freeze. Only `fix/` PRs merge.
- TD-1h: tag `v1.0.0-rc.1`. Fresh-clone check: `git clone <repo> /tmp/c && cd /tmp/c && pip install -r requirements.txt && uvicorn app.main:app`.
- TD-15m: tag `v1.0.0`. No pushes to `main` after this unless the human says so.

## 11. When something goes wrong

- Bad commit on `main`: `git revert <sha>`. Never reset.
- Conflict you don't understand: stop and show your human both sides.
- Pushed a secret: tell the human now and rotate the key; deleting the commit is not enough.
- Lost work: `git reflog` first.

## 12. Report after every push

Branch, commits (short sha + summary), files changed, checks run and results, anything skipped or risky.
