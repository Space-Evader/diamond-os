# Supervised cycles and bounded workers

Run from the repository root with Python 3.10+ on Linux. Offline operation uses
only the standard library. The 24 recovered files remain unchanged.

```sh
python -B diamond-core/learning_cycle.py demo --store /tmp/diamond-cycle-demo
python -B diamond-core/learning_cycle.py demo --store /tmp/diamond-cycle-demo
python -B diamond-core/agent_coordinator.py --demo --destination /tmp/diamond-worker-demo
python -B -m unittest discover -s diamond-core -v
```

The demo invents two representative evidence excerpts. It does not retrieve
Nautilus reporting or prove any benefit. First execution stages two packets,
checks duplicate replay, records an analogy, and records `needs_work` feedback.
Re-running the same completed cycle returns its receipt without reverting newer
source revisions. Interrupted cycles resume from individual atomic records.
Receipts and private evidence stay outside Git in user-only directories.

For selected real input, use a JSON plan and two to eight selected envelopes:

```sh
python -B diamond-core/learning_cycle.py run --store /private/reviews \
  --plan /private/plan.json --input /private/selected-a.json \
  --input /private/selected-b.json --confirm-review-only
```

`demo_inputs()` in `learning_cycle.py` supplies a complete example plan and
envelopes. A plan uses schema `diamond.cycle/1`, `input_kind` (`synthetic` or
`real`), a fixed timezone-bearing `reviewed_at`, `projects`, `reviewer`,
`instruction_ref`, `synthesis` (`relation`, `hypothesis`, `challenge`, `next_step`),
and `feedback` (`decision`, `note`). Keep its time stable for retry. An envelope
has only `source` and `approval`, as emitted by the recovered selector. The
registry checks exact approved source identities; this does not verify claims.
Both source and plan provenance are operator declarations, not authentication.

The source selector is available through a secure wrapper:

```sh
python -B diamond-core/learning_cycle.py select --source nautilus --id EXACT_ID \
  --account-ref STABLE_NON_SECRET_LABEL --instruction-ref EXPLICIT_SELECTION \
  --token-file /private/oauth/authorized.json --store /private/selected \
  --confirm-review-only
```

This reuses `gmail_review_select.select_approved`, including sender and message
identity checks before and after body retrieval. The token and store must be
outside Git; on POSIX the token must be user-only and its directory mode 0700.
It uses existing read-only authorization, starts no OAuth browser flow, and never
writes tokens into the source tree. Refreshed credentials remain in memory.
Live selection through the wrapper additionally needs `google-auth` and
`google-api-python-client`; the recovered direct OAuth flow also imports
`google-auth-oauthlib`. Offline tests need none of these. No credentials or live-mailbox
selection are supplied by this change. Selection publication remains create-only.

## Worker contract

`agent_coordinator.py --tasks /private/tasks.json --destination /private/runs`
executes a JSON list of one to eight tasks against a bounded trusted Python
snapshot. Each task has `id`, `role`, `action`, and `payload`, with optional
`depends_on` referencing earlier task IDs. Failed prerequisites block downstream
execution. Unknown capabilities escalate to a supervisor; no automatic privilege
expansion or external specialist is invoked.

| Role | Action | Payload and result |
| --- | --- | --- |
| coding | propose_edit | One top-level `.py` path, `expected_sha256`, unique `before`, `after`; outputs a syntax-checked patch for supervisor review, never applies it to the repository |
| research | extract | `selected` envelopes, `projects`, `reviewed_at`, `input_kind`; outputs unresolved assertion counts and packet hashes |
| testing | unittest | `pattern`, e.g. `test_acceleration_independent.py`; executes trusted tests and reports counts, skips, failures and errors |
| intelligence | cycle | `plan` and `selected`; executes a complete private review-only learning cycle |

The demo actually executes all four local worker processes, then exits. They are
fixed deterministic handlers, not model agents or installed background workers.
Coding proposals are not automatically applied; testing examines the original
snapshot. Reports include source fingerprints, permissions, actual start status,
results and escalation reasons. Failure, timeout or blocked work makes the CLI
exit nonzero. Private logs and task snapshots remain under the run directory.

Each process has its own copy, a scrubbed environment, a 1–60 second wall budget,
25 CPU seconds, 512 MiB address space and 8 MiB per-file output limit. Python
audit guards deny network and access outside task state/runtime libraries, and
only permit the fixed recovered growth-link test subprocess. These are
application guards for trusted code, **not an OS sandbox for hostile Python**.
The current host rejected the namespace-sandbox probe. Use external sandboxing
before executing untrusted code. Windows worker execution is not verified.
Coordinator integration tests are skipped inside workers to prevent recursive
worker dispatch; run the full suite on the supervising host.

All extracted claims remain `UNRESOLVED`; connections remain hypotheses and all
stored records have `canonical=False`, `review_required=True`. Neither a positive
feedback decision nor a source instruction can promote memory. No canonical
promotion, scheduler, deployment or mail modification operation is exposed.
