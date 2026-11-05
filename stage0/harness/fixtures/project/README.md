# Stage 0 synthetic project: artifact release gate

This directory is a synthetic project fixture. It is not a real business project and
contains no real data, credentials, or personally identifying information.

The toy system controls one state transition: a draft artifact may become `released`
only when a `release_manager` approves it. A contributor approval is advisory and must
not release the artifact.

The policy is stated in `docs/RELEASE_POLICY.md`. `src/release_gate.py` is a toy
implementation used only to give the synthetic task a project-shaped source tree.
