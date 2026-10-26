# Real selected-message reviews

Connected Gmail tools can search one allowed sender, read the selected message's
metadata, check the exact From identity, then read only that message. Reuse that
connection: no OAuth token needs to enter the coding environment. If using a
standalone Gmail client, the minimum body-reading scope is `gmail.readonly`;
metadata-only access cannot read the evidence. No send or modify permission is
needed. This implementation requests no scopes and performs no mailbox writes.

Save connector results or operator exports in a private directory outside Git:

```sh
python -B diamond-core/gmail_import.py \
  --selection /private/selection.json --metadata /private/metadata.json \
  --message /private/message.json --store /private/selected --confirm-review-only
python -B diamond-core/learning_cycle.py review-one \
  --plan /private/review-plan.json --input /private/selected/gmail_approved_HASH.json \
  --store /private/reviews --confirm-review-only
```

`selection.json` has exactly `schema: diamond.gmail-selection/1`, `source_id`,
`message_id`, a stable nonsecret `account_ref`, `instruction_ref`, timezone-bearing
`captured_at`, and `transport` (`connected_gmail` or `operator_export`). Metadata
and full snapshots use Gmail's message ID, payload and headers. Both Google API
camelCase and connector snake_case plain-text MIME representations are supported
by the recovered selector helpers. Both snapshots must match the selected ID and
one exact approved From mailbox. The CLI rejects bad metadata before opening the
body file. Attachments and HTML-only messages remain excluded. It never follows
links, runs source instructions or fetches other messages. Reimport of the same
capture is idempotent; conflicting captures fail closed.

Snapshots and transport labels are operator declarations, not cryptographic
authentication. The importer cannot prove that an exported JSON file came from
Gmail. A connected-tool run must separately record its actual retrieval evidence;
never label a synthetic fixture or manually fabricated snapshot as live capture.

A single-message plan has schema `diamond.single-review/1`, `input_kind`
(`real` or `synthetic`), `reviewed_at`, `projects`, `reviewer`, `instruction_ref`,
one to three `evidence_spans` (`start`, `end` character offsets into the extracted
plain-text body), `review` (`hypothesis`, `challenge`, `application`), and
`feedback` (`decision`, `note`). See `fixture()` in `test_real_learning.py` for a
complete synthetic schema example. Source and review approvals are declarations,
not owner identity authentication or authorization to promote memory.

The command reuses existing bounded extraction, replaces candidate spans with the
operator's exact selections, stages one noncanonical packet and records feedback
against its hash. It does **not** create a fake second source or a corroboration
connection. All excerpts remain `UNRESOLVED` and all hypotheses require owner
review. CLI output contains counts/hashes; a private `review_HASH.json` contains
short evidence excerpts, source metadata, proposed application and feedback.
Full message text, subscription links and raw MIME snapshots stay out of Git,
PRs and public reports. Canonical promotion is unavailable.

## Coordinator handoffs

Use the existing `agent_coordinator.py`, with these additional bounded actions:

- Research `prepare_review`, payload `{plan, selected}`: validates the selected
  evidence and exact review spans, then writes one private, hashed handoff.
- Intelligence `review_single`, payload `{from_task: RESEARCH_ID}`, with
  `depends_on: [RESEARCH_ID]`: consumes that successful handoff and executes the
  existing single-source review. No new Gmail access is delegated.
- Testing `unittest`, payload `{pattern, proposal_from: CODING_ID}`, with
  `depends_on: [CODING_ID]`: validates the coding worker's proposed-file hash and
  original-source hash, then tests that proposal in the testing snapshot. It
  never applies the edit to the repository. Omit `proposal_from` for unchanged
  snapshot testing.

Handoff artifacts have fixed filenames, bounded size and checked content hashes.
Failed prerequisites block execution. Arbitrary paths, mixed inline/handoff
evidence, stale source proposals and tampered artifacts fail closed and request
specialist review. These hashes detect changes, not malicious authorship.
The workers remain fixed local processes for trusted source, not autonomous model
agents or hostile-code sandboxes. Existing time, memory, file, network and
repository-write restrictions remain in effect.
