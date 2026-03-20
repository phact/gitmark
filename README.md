# gitmark

Assign uncommitted working tree changes to named commits, then execute them in sequence with optional per-commit checks.

## Installation

```bash
pip install gitmark
```

## Usage

See `gitmark-spec.md` for full documentation.

Basic workflow:

```bash
# View uncommitted changes
gitmark diff

# Assign hunks to named commits
gitmark mark auth-refactor auth/token.py:14-67 db/models.py:8
gitmark mark rate-limiting auth/token.py:102

# Set commit messages
gitmark message auth-refactor "refactor: extract token validation logic"
gitmark message rate-limiting "feat: add rate limiting"

# Execute all commits
gitmark commit
```
