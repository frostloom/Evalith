# Release Approval Agent

A small synthetic project used by the Evalith stage-1 walkthrough. It is not a
real business system and contains no real credentials.

The agent receives a release request for an artifact and decides whether the
release may proceed. A contributor may open a request, but only a release
manager may approve it. The release is recorded in an audit file.

## Run

The demo runs as an HTTP handler:

```text
POST /release
{"artifact_id": "doc-18", "actor": "alice", "role": "release_manager"}
```

See `docs/release-policy.md` for the policy and `src/approval.py` for the
current implementation.

## Known gaps

- The current implementation checks the role passed in the request and trusts
  the caller to supply it.
- There is no test data for rejected requests yet.
