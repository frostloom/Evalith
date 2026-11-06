# Customer Support Reply Agent

A second synthetic project for the Evalith stage-1 walkthrough. It is a
conversation-style agent, unlike the release-approval example. It contains no
real customer data and no real credentials.

The agent receives a customer message and a short account summary, then drafts a
reply. It must not promise refunds, must cite the policy section when declining,
and must hand off account closures to a human.

## Interface

```text
POST /reply
{"message": "...", "account": {"plan": "pro", "status": "active"}}
```

See `docs/tone-guide.md`, `prompts/system.md` and `src/reply.py`.

## Known gaps

- The current code does not check whether the customer is asking to close the
  account.
- The FAQ fixture has no refund policy text yet.
