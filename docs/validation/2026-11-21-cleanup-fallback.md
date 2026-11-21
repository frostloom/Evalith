# Cleanup fallback verification

## Problem

`bounded_process` recorded the first `SIGTERM` failure as the final cleanup result. If the process was still running and the subsequent `SIGKILL` succeeded, the observation still reported `cleanup_status=failed`. This could turn a successfully cleaned process into a false execution error.

## Root cause

The graceful-termination error was written directly to `cleanup_error`. The forced-kill fallback only replaced that value when it also failed, so a successful `SIGKILL` left the earlier error intact.

## Fix

- A failed `SIGTERM` now proceeds to the forced `SIGKILL` fallback instead of deciding cleanup status immediately.
- The final `SIGKILL` outcome determines whether cleanup succeeded.
- After a successful forced kill, `process.wait(timeout=3)` reaps the child and records its final return code.
- A failed forced kill, or a forced kill that cannot be reaped, still reports `cleanup_status=failed` with the system error.

## Regression evidence

The failing test initially produced:

```text
assert observed["cleanup_status"] == "completed"
E AssertionError: assert 'failed' == 'completed'
```

After the fix, both cleanup cases pass:

```text
evalith/tests/test_execution_process.py .. [100%]
2 passed
```

The two cases cover:

1. Final cleanup failure remains visible as `cleanup_status=failed`.
2. `SIGTERM` failure followed by a successful `SIGKILL` reports `cleanup_status=completed`.

Full validation on the fix:

- Backend: **300 passed**
- Frontend: **58 passed**
- TypeScript/Vite build: passed
- Ruff static gate: passed
- Git whitespace check: passed
