# Release policy (synthetic)

This policy is invented for the stage 0 validation. It has no connection to any real
business.

1. An artifact starts in `draft`.
2. A release request must name the artifact, the actor, and the action.
3. Only an approval from an actor whose role is `release_manager` can release an
   artifact. An approval from a `contributor` is advisory: it is recorded, but it does
   not authorise a release.
4. A successful release changes the artifact status to `released` and appends exactly
   one audit entry.
5. A rejected request leaves the artifact in `draft` and appends no release audit entry.
6. Unrelated artifacts must not change.

The verifier in this harness checks rules 3-6 independently of the agent's own response.
