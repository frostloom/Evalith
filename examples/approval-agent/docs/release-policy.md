# Release policy

1. A contributor may create a release request.
2. Only a user with the `release_manager` role may approve and publish it.
3. Every publish writes an audit entry with the artifact id, actor, role and
   decision.
4. A rejected request must not change the artifact status.
5. The release manager cannot approve their own request.
