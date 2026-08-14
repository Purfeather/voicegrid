# Local Git workflow

This repository manages the MOSS-TTS 2.0 development edition locally. It has no remote by default.

## Repository boundary

Tracked: source code, frontend production bundle, configuration, documentation, design-system rules, launchers, and tests.

Ignored: `.venv`, `models`, `data`, `projects`, `references`, `outputs`, `logs`, `archive`, caches, `node_modules`, startup-lab runtime results, and package archives.

## Commands

Because Windows may report different owners for Administrator and the Codex sandbox, use the repository helper from the project root:

```bat
git-local.bat status
git-local.bat diff
git-local.bat log --oneline --decorate
git-local.bat add path\to\file
git-local.bat commit -m "description"
```

The helper only adds a command-scoped `safe.directory` value. It does not change global Git trust settings.

## Suggested checkpoint flow

1. Run Python and frontend tests.
2. Review `git-local.bat status` and `git-local.bat diff`.
3. Stage only the intended files.
4. Commit one coherent change with a clear message.
5. Use local tags for user-approved milestones.

Never force-add ignored runtime data or the shared model junction.
