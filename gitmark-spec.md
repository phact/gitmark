# gitmark — Specification

## Overview

`gitmark` is a third-party CLI tool installable via `pip install gitmark`. It lets a developer or AI agent assign uncommitted working tree changes to named commits, then execute them in sequence with optional per-commit checks. It sits on top of git and uses standard git plumbing (`git diff`, `git apply`, `git stash`) under the hood.

The primary use case is an AI coding agent that has finished making changes across many files and wants to produce a clean, reviewable PR with logical commits rather than one blob. The agent already has the context to know why it touched each file — gitmark gives it a way to express that into git history.

---

## Core Concepts

### Hunk
A contiguous block of changed lines in a file, as produced by `git diff`. The natural unit of assignment.

### Hunk Address
The way a hunk (or range of hunks) is referenced on the command line. Three forms:

```
auth/token.py              # entire file — all hunks in it
auth/token.py:14           # single hunk starting at line 14
auth/token.py:14-67        # all hunks whose start line falls within this range
```

Hunk addresses are always relative to the repo root, matching exactly what `git diff` shows.

### Named Commit (tag)
A short kebab-case identifier used as a working handle throughout the planning phase, e.g. `auth-refactor`, `rate-limiting`, `db-cleanup`. The tag is not the commit message — it's just a stable reference for the CLI. The actual commit message is set separately.

### Plan
The full set of named commits with their assigned hunks, exec commands, and messages. Stored in `.git/gitmark` as a simple JSON file. The user never edits this file directly — all interaction is through the CLI.

---

## Commands

### `gitmark diff`

Show all uncommitted changes with assignment state overlaid. This is `git diff` output reformatted to show hunk addresses and which tag (if any) each hunk is assigned to.

```
auth/token.py
  :14  +8  -4   def validate_token(token: str) -> bool:    → auth-refactor
  :45  +18 -0   class RateLimiter:                         → rate-limiting
  :88  +2  -1   return HttpResponse(...)                   ✗ unassigned

db/models.py
  :8   +11 -3   class User(BaseModel):                     → auth-refactor

api/routes.py
  :102 +24 -1   @router.get("/auth")                       ✗ unassigned
```

Unassigned hunks are visually distinct (color: yellow or red). Assigned hunks show the tag they belong to.

**Scoped view:**

```bash
gitmark diff auth-refactor
```

Shows only the hunks assigned to `auth-refactor`, with full diff context. Useful for reviewing a commit before executing.

---

### `gitmark mark <tag> <hunk-address> [<hunk-address> ...]`

Assign one or more hunks to a named commit. Creates the tag if it doesn't exist yet. Can be called multiple times on the same tag to add more hunks incrementally.

```bash
gitmark mark auth-refactor auth/token.py:14-67 db/models.py:8
gitmark mark auth-refactor auth/token.py:88        # add more later
gitmark mark rate-limiting auth/token.py:102
gitmark mark api-cleanup api/routes.py             # whole file
```

**Errors:**
- Hunk address does not match any changed hunk → error with suggestion of nearest match
- Hunk already assigned to a different tag → error, show which tag owns it

---

### `gitmark unmark <tag> <hunk-address> [<hunk-address> ...]`

Remove hunk assignment(s) from a named commit. Hunks return to unassigned state.

```bash
gitmark unmark auth-refactor auth/token.py:88
```

---

### `gitmark exec <tag> "<shell command>"`

Attach an exec command to a named commit. The command is run after this commit's hunks are applied and isolated, before the commit is finalized. Any valid shell command is accepted — exit 0 means pass, non-zero means fail.

```bash
gitmark exec auth-refactor "pytest tests/auth/"
gitmark exec rate-limiting "make lint && pytest tests/rate/"
gitmark exec frontend "npm run test"
gitmark exec db-migration "python manage.py migrate --check && pytest tests/db/"
```

Each tag can have one exec command. Calling `exec` again on the same tag overwrites it. Exec is optional — tags without one commit unconditionally.

---

### `gitmark message <tag> "<message>"`

Set the commit message for a named commit without executing it. Used in the bulk flow when you want to set all messages upfront and execute everything at once with `gitmark commit`.

```bash
gitmark message auth-refactor "refactor: extract token validation logic"
gitmark message rate-limiting "feat: add rate limiting to auth endpoints"
```

---

### `gitmark reset <tag>`

Remove a named commit and all its hunk assignments from the plan entirely. The hunks return to unassigned state.

```bash
gitmark reset api-cleanup
```

---

### `gitmark status`

Show the full current plan: all named commits, their assigned hunks, exec commands, and whether a message has been set. Unassigned hunks are listed at the bottom.

```
PLAN

  auth-refactor
    message : "refactor: extract token validation logic and update user model schema"
    exec    : pytest tests/auth/
    hunks   : auth/token.py:14-67  auth/token.py:88  db/models.py:8

  rate-limiting
    message : (not set)
    exec    : make lint && pytest tests/rate/
    hunks   : auth/token.py:102

UNASSIGNED
    api/routes.py:102
    api/routes.py:134
```

`gitmark` with no arguments is equivalent to `gitmark status`.

---

## The Two Commit Flows

### Sequential flow — mark and commit one at a time

The agent commits each named commit immediately as it goes. Order is explicit — whatever order `gitmark commit <tag> -m` is called is the order commits appear in git history.

```bash
gitmark mark auth-refactor auth/token.py:14-67 db/models.py:8
gitmark exec auth-refactor "pytest tests/auth/"
gitmark commit auth-refactor -m "refactor: extract token validation logic"
# auth-refactor is now in git history

gitmark mark rate-limiting auth/token.py:102
gitmark exec rate-limiting "make lint && pytest tests/rate/"
gitmark commit rate-limiting -m "feat: add rate limiting to auth endpoints"
# rate-limiting is now in git history
```

### Bulk flow — plan everything then execute

The agent marks all hunks and sets all messages upfront, then executes the whole plan at once. Commits execute in the order tags were first created (first `mark` call wins).

```bash
gitmark mark auth-refactor auth/token.py:14-67 db/models.py:8
gitmark mark rate-limiting auth/token.py:102

gitmark exec auth-refactor "pytest tests/auth/"
gitmark exec rate-limiting "make lint && pytest tests/rate/"

gitmark message auth-refactor "refactor: extract token validation logic"
gitmark message rate-limiting "feat: add rate limiting to auth endpoints"

gitmark commit        # executes all in plan order
```

---

### `gitmark commit <tag> -m "<message>"`

Execute a single named commit immediately. Sets its message and commits in one step. Used in the sequential flow.

```bash
gitmark commit auth-refactor -m "refactor: extract token validation logic"
```

For each commit, gitmark:
1. Applies its hunks to the index via `git apply --cached`
2. Stashes everything not in the index (`git stash --keep-index`) to isolate this commit
3. Runs its exec command if set — on non-zero exit, bails out (see Failure Behavior)
4. Pops the stash (`git stash pop`)
5. Creates the git commit with the set message
6. Removes the tag from the plan

---

### `gitmark commit`

Execute all named commits in the plan in order. Each commit must have a message set via `gitmark message` beforehand — otherwise gitmark refuses and lists the offending tags.

Output:

```
executing plan  (3 commits)

  [1/3] auth-refactor
        hunks   : auth/token.py:14-67  db/models.py:8
        exec    : pytest tests/auth/
        applying...  ✓
        isolating... ✓
        running...   ✓  (47 tests passed)
        committed    abc1234  "refactor: extract token validation logic"

  [2/3] rate-limiting
        hunks   : auth/token.py:102
        exec    : make lint && pytest tests/rate/
        applying...  ✓
        isolating... ✓
        running...   ✗  FAILED

        exec command exited with code 1:
        ───────────────────────────────
        FAILED tests/rate/test_limiter.py::test_burst_limit
        ───────────────────────────────

        gitmark: bailing. repo restored to pre-commit state.
        commits already applied : auth-refactor
        remaining               : rate-limiting, api-cleanup
        fix the issue and re-run: gitmark commit
```

**Before executing**, `gitmark commit` refuses and prints a summary if:
- Any named commit has no message set
- Any changed hunk is unassigned (override with `--allow-unassigned`)

**Failure behavior:**
- On exec failure, stash is popped, index is cleared, no commit is made for the failing tag
- Commits already applied in this run remain in git history — they passed, they stay
- The plan is updated to remove already-committed tags so re-running picks up from the failure point

---

### `gitmark commit --edit`

Before executing, dump the full plan to `$EDITOR` as JSON. On save, re-read and execute. Allows reordering commits, editing messages, and adjusting exec commands in one pass. Same format as `.git/gitmark`.

---

## Error Cases

| Situation | Behavior |
|---|---|
| Hunk address matches nothing | Error + show `gitmark diff` |
| Hunk address ambiguous (overlapping ranges) | Error + list matched hunks, ask to be more specific |
| Hunk already assigned to another tag | Error + show owning tag |
| `gitmark commit` with unset messages | Refuse + list offending tags |
| `gitmark commit` with unassigned hunks | Refuse + list them (override with `--allow-unassigned`) |
| Exec command fails | Bail + restore working tree + report exit code and output |
| Merge conflict during apply | Bail + restore + explain which hunk conflicted |

---

## Implementation Notes

- **Language:** Python, installable via `pip install gitmark`
- **Distribution:** Third-party tool, not a git extension. Invoked as `gitmark`, not `git mark`
- **Git interaction:** Shell out to git commands directly — do not use a git library. Commands used: `git diff`, `git apply --cached`, `git stash`, `git stash pop`, `git commit`
- **Hunk parsing:** Parse `git diff` output directly to build the hunk map
- **Dependencies:** Nothing outside Python stdlib except ANSI color output (use `colorama` or raw ANSI codes)
- **Portability:** Must work in any git repo regardless of language, framework, or OS
- **State:** `.git/gitmark` is added to `.git/info/exclude` automatically on first write so it never appears as an untracked file
- **State cleared:** `.git/gitmark` is deleted automatically after a fully successful `gitmark commit` run
# gitmark — Backup & Restore

## Overview

Before executing any commit operation, gitmark snapshots the full working tree to a temporary branch. This protects uncommitted work from any bugs in gitmark itself. The snapshot is always restorable with a single command.

---

## Backup Behavior

At the start of every `gitmark commit` invocation (both `gitmark commit` and `gitmark commit <tag> -m`), before touching the index or running any git commands, gitmark automatically:

1. Stashes the working tree (`git stash`)
2. Creates a backup branch off the current HEAD: `gitmark/backup-{timestamp}`
3. Pops the stash onto the backup branch (`git stash pop`)
4. Commits everything — staged and unstaged — to the backup branch (`git add -A && git commit`)
5. Returns to the original branch with the working tree intact

The backup branch name format: `gitmark/backup-20250320-143022`

The `gitmark/` namespace groups all backup branches together in `git branch` output, making them easy to identify and prune.

**The backup is silent by default.** Gitmark prints a single line on success:

```
✓ backup created: gitmark/backup-20250320-143022
```

---

## Cleanup

Backup branches are not deleted automatically. After a fully successful `gitmark commit` run, gitmark prompts:

```
delete backup branch gitmark/backup-20250320-143022? [y/N]
```

Default is no — the backup is kept unless explicitly confirmed. Users can also prune all backup branches manually:

```bash
git branch | grep gitmark/backup | xargs git branch -D
```

---

## `gitmark restore`

Restore the working tree to the state captured in the most recent backup branch, discarding all changes made since.

```bash
gitmark restore
```

Output:

```
restoring from gitmark/backup-20250320-143022...

  this will discard all changes since the backup was created.
  current branch: main
  backup taken  : 2025-03-20 14:30:22

  continue? [y/N]
```

On confirmation:

1. Resets the current branch to match HEAD
2. Checks out the backup branch
3. Soft-resets to its parent (the pre-backup HEAD), leaving all changes in the working tree
4. Returns to the original branch with the working tree restored

The plan state (`.git/gitmark`) is also restored to the snapshot taken at backup time.

**Restore to a specific backup:**

```bash
gitmark restore gitmark/backup-20250320-143022
```

**List all backups:**

```bash
gitmark restore --list

  gitmark/backup-20250320-143022   main   2025-03-20 14:30:22
  gitmark/backup-20250319-091144   main   2025-03-19 09:11:44
```

---

## Error Cases

| Situation | Behavior |
|---|---|
| Backup branch creation fails | Abort — do not proceed with commit |
| `gitmark restore` with no backups found | Error: no backup branches found |
| Working tree has conflicts during restore | Error + instructions to resolve manually |
| Backup branch was manually deleted | Error: named backup not found, list available backups |
