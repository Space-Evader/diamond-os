# Applied intelligence and behavioral proof

Existing source selection, private import, single-source review, feedback and
bounded coordinator components remain the execution path. No mailbox permissions,
new source identities, external agent systems or canonical promotion are added.

`evidence_relations.py` compares current packet excerpts referenced by reviewed
cards: `id`, `packet_hash`, `idea_index`, `story_key`, `claim_key`, `stance`
(`supports`, `disputes`, `uncertain`). Exact-text repeats are automatic; semantic
story keys, claim scope and reported stance require operator review. It reports
repeated story references, exact excerpt repetitions and opposing reported claims
without deciding which party is correct. More messages are not more truth.

Independent support requires an explicit named review of two distinct reporting
origins, distinct conservative publisher buckets, distinct source lineages and
different reporting excerpts supporting the same claim. Related AI newsletters
share a conservative independence bucket. Bucket labels cannot be overridden by
caller annotations. This is a conservative guard, not proof of legal ownership.
Even assessed independent support leaves claims unverified and noncanonical.

Run `python -B diamond-core/evidence_relations.py /private/analysis-input.json`
with private `packets`, `cards` and optional `independence_reviews`. The latter
records `cards`, `publisher_groups`, `origin_refs`, `reviewer` and `rationale`.
Snapshot and reviewer declarations are not authentication.

`rank_candidates()` accepts grounded proposals with uncertainty, project,
evidence card references, an estimated effort range and operator value/risk
ratings. Priority is value divided by risk and upper effort estimate. It does not
estimate revenue or increase confidence with duplicated sources. Existing
usefulness-feedback events are attached to the next ranking for review; positive
local outcome feedback never verifies a publisher's claims or promotes memory.

## Implemented improvement: executable CLI proof

Create a private coordinator task list:

```json
[{"id":"behavior-proof","role":"testing","action":"verify_cycle_cli","payload":{}}]
```

Then run:

```sh
python -B diamond-core/agent_coordinator.py --tasks /private/tasks.json --destination /private/proof-runs
```

This fixed operation executes the existing learning-cycle demo CLI twice, verifies
first-run ingestion and duplicate checks, then checks receipt replay and actual
stored state: two packet revisions, one connection, one feedback event and zero
canonical records. It writes `behavior-proof.json` with output hashes. It accepts
no arbitrary command arguments, never modifies a repository, and remains inside
the coordinator's time/resource and trusted-code boundaries. A failed proof is a
failed testing task; it does not open, merge or deploy a PR. Use this check before
requesting review; it is not installed as an automatic GitHub branch rule.

The controlled regression changes only the CLI dispatch to print a fake success
object while leaving functions intact. Fifteen existing function tests pass that
broken snapshot; this gate rejects it and writes no success proof. A healthy
snapshot passes. This is one deliberately injected failure, not a general bug
detection rate or measured business outcome. The CLI proof uses synthetic input,
separately from the real selected-message research batch.

Run all tests with `python -B -m unittest discover -s diamond-core -v`.
Private message bodies, captured IDs, rankings and outcome records belong outside
Git. Human review, privacy boundaries and canonical-memory approval still apply.
