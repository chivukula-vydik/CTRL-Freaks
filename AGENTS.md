# AGENTS.md: Git and Versioning Rules

Every AI agent working in this repo (Claude Code, Cursor, Copilot, Codex, Windsurf, etc.) must follow these rules. They are not suggestions. If a rule blocks you, stop and ask the human. Do not work around it.

## 0. Project commands

```
INSTALL:  pip install -r requirements-dev.txt
LINT:     <none configured>
FORMAT:   <none configured>
TEST:     pytest -q  &&  python eval/run_eval.py --label <x>
RUN:      uvicorn app.main:app --reload   (UI: API_URL=http://localhost:8000 streamlit run ui/app.py)
DEADLINE: <YYYY-MM-DD HH:MM IST>
```

## 1. Branches

- `main`: demo / submission branch. Always runnable. Never commit directly.
- `dev`: integration branch. All feature work merges here first.
- Feature branches come off the latest `dev`, named `<type>/<owner>-<short-desc>`
  - e.g. `feat/vydik-auth-api`, `fix/ravi-login-crash`
  - types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `hotfix`
- One branch = one task. Do not mix unrelated changes.
- Delete the branch after it is merged.

## 2. Before starting work

```bash
git fetch origin
git switch dev && git pull --ff-only
git switch -c feat/<owner>-<desc>
git log --oneline -15 origin/dev      # see what changed recently
```

- Check `TASKS.md` so you don't edit files another open branch has claimed (see section 8).

## 3. Commits

Format (Conventional Commits):

```
<type>(<scope>): <imperative summary, max 72 chars>

<optional body: why, not what>

Agent: <tool-name>
```

Examples:
```
feat(auth): add JWT refresh endpoint
fix(dashboard): handle empty portfolio response
chore(deps): bump fastapi to 0.115.2
```

- Small and atomic: one logical change per commit. If the summary needs "and", split it.
- Every commit must build. No `WIP` commits on shared branches (squash first).
- Always add the `Agent:` trailer so humans can trace who changed what.
- Never commit: `.env`, API keys, tokens, passwords, private keys, `node_modules/`, `venv/`, build output, datasets, model weights, any file over 5 MB. Confirm `.gitignore` covers them.

## 4. Pre-push checklist (all must pass)

1. `git fetch origin && git rebase origin/dev`. Resolve conflicts properly. Never drop someone else's changes just to make a conflict go away.
2. INSTALL succeeds on a clean state.
3. LINT and FORMAT pass, only on files you touched.
4. TEST passes. If there are no tests, RUN starts and the core flow works.
5. `git diff origin/dev --stat`: only files your task needed are changed.
6. Secret scan: `gitleaks detect` if available, otherwise
   `git diff origin/dev | grep -iE "api[_-]?key|secret|token|password|BEGIN .*PRIVATE KEY"` returns nothing real.
7. `CHANGELOG.md` updated under `[Unreleased]`.

Then: `git push -u origin <branch>`

## 5. Forbidden without explicit human approval

- `git push --force` / `-f` on any shared branch. On your own branch use `--force-with-lease` only.
- `git reset --hard`, `git clean -fd`, `git checkout -- .`, `git stash drop` on work you didn't create.
- Rewriting pushed history on `main` or `dev` (rebase, amend, squash).
- Merging anything into `main`.
- Deleting branches or tags you didn't create.
- Editing CI config, `.gitignore`, branch protection, repo settings.
- Editing lockfiles unless the task is a dependency change.
- Major version bumps of dependencies.
- Deleting or renaming files outside your task scope.
- Reformatting files you didn't otherwise change.
- Disabling, skipping, or deleting tests or CI checks to get green.

## 6. Pull requests

- Target `dev`. Title in Conventional Commit format.
- Body must have: what changed, why, how it was tested, screenshots for UI changes, known gaps.
- Squash merge.
- A human approves before merge. Agents never self-merge.
- If CI fails, fix the cause. Don't bypass it.

## 7. Versioning (SemVer)

Format `vMAJOR.MINOR.PATCH`. Stay on `0.x` during the hackathon.

| Bump  | When                                   | Example  |
|-------|----------------------------------------|----------|
| PATCH | bug fix, no new feature                | `v0.3.1` |
| MINOR | new feature / demoable milestone       | `v0.4.0` |
| MAJOR | final submission                       | `v1.0.0` |

Release flow (human-triggered only):
1. PR `dev` -> `main`, merged by a human.
2. Move `[Unreleased]` in `CHANGELOG.md` to a new version heading with date and time.
3. Bump the version in `package.json` / `pyproject.toml` / `__version__`.
4. Annotated tag and push:
   ```bash
   git tag -a v0.4.0 -m "v0.4.0: <milestone>"
   git push origin v0.4.0
   ```

Rules:
- Tag every build that gets demoed or judged (checkpoint rounds), so you can roll back.
- Never move or delete an existing tag.
- Hotfix: `hotfix/<desc>` off `main` -> PR to `main` -> tag PATCH -> merge `main` back into `dev`.

## 8. Multi-agent coordination

- Claim before you code: add a line to `TASKS.md` with branch name, owner, and files/modules you'll touch. Remove it once merged.
  ```
  - feat/vydik-auth-api | vydik | backend/auth/*, backend/routes.py
  ```
- Don't edit files claimed by another open branch. Ask the human if you must.
- Shared hotspots (lockfiles, DB schema/migrations, route index, global config, env templates): one change at a time, merge fast, tell others to rebase.
- Never edit an existing DB migration. Add a new one.
- Rebase on `dev` after every merge into `dev`, and at least every 2 hours.

## 9. CHANGELOG.md format

```
## [Unreleased]
### Added
- feat(auth): JWT refresh endpoint
### Fixed
- fix(dashboard): empty portfolio crash
### Changed

## [0.3.0] - 2026-10-31 14:20
...
```

## 10. Deadline rules

- **T-2h**: feature freeze. Only `fix/` branches merge into `dev`.
- **T-1h**: `main` frozen except human-approved hotfixes. Tag `v1.0.0-rc.1`.
- **T-15m**: tag `v1.0.0`. Verify a fresh clone builds and runs:
  ```bash
  git clone <repo> /tmp/check && cd /tmp/check && <INSTALL> && <RUN>
  ```
- **Last 10 minutes**: no pushes to `main` unless the human says so.

## 11. When something goes wrong

- Bad commit on a shared branch: `git revert <sha>`. Never reset.
- Conflict you don't understand: stop and show the human both sides.
- Pushed a secret: tell the human immediately and rotate the key. Removing the commit is not enough.
- Lost work: run `git reflog` before anything else.
- Build broken on `dev`: fixing it is the top priority for whoever broke it. Revert if the fix takes more than 15 minutes.

## 12. Report after every push

Reply to the human with:
- branch name
- commits (short sha + summary)
- files changed
- checks run and results
- anything skipped, risky, or left TODO
