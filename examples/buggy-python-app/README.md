# Buggy Python App

Small deterministic target for FixProof development.

## Issue

`validate_refresh_token()` incorrectly accepts an access token and rejects a refresh token because the token-type check is inverted.

## Expected behavior

- `refresh:*` token -> accepted
- `access:*` token -> rejected

## Run

```bash
python -m pytest -q
```

The starter intentionally contains a failing test. M1 will use this kind of target to establish the red/green repair loop in an isolated workspace.
