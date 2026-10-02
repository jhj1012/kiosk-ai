# Contributing

## Workflow

1. Pick or create an issue on GitHub.
2. Create a branch from `main`: `feature/<short-name>`, `fix/<short-name>`, or `docs/<short-name>`.
3. Commit small, focused changes. `pre-commit` runs `ruff` automatically.
4. Open a pull request to `main`. At least one teammate reviews it.
5. CI must pass (lint, architecture check, tests) before merging.

## Rules

- `assistant/` must **never** import `kiosk_app/`. The assistant only talks to the screen.
- Never commit API keys, audio recordings, or `.env` / `*.local.yaml` files.
- Changing the Gemini model or its settings = edit `configs/models.yaml` in a PR, and tell the team.
- Add dependencies with `uv add --group <kiosk|assistant|dev> <package>` and commit `uv.lock`.
- Every interactive widget in `kiosk_app` needs an `accessibleName`.
