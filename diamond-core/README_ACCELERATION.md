# Diamond Core — Operation Acceleration

Recovered audit base: 1914464b37ed90fceb567004324ced27e80384e5.
Branch: feature/operation-acceleration-20261025.
This is not the inaccessible Windows checkpoint 1b0d2eb. Existing universe.py
and legacy Gmail controls are preserved.

## Working commands

    python -B -m unittest discover -v
    python learning_pipeline.py --store /path/to/private/reviews status
    python learning_pipeline.py --store /path/to/private/reviews ingest /path/to/selected.json --project "Diamond Core" --analyst "Diamond extractive worker" --confirm-review-only
    python learning_pipeline.py --store /path/to/private/reviews duplicates
    python growth_links.py list
    python growth_links.py link --product beautiful-mind --source instagram --medium organic_social --campaign founder-review

Python 3.10+; offline pipeline and tests need no third-party dependencies.
Gmail selection retains the existing optional Google OAuth dependencies.
No credentials are included; no live local OAuth startup was performed.

    python gmail_review_select.py list --query "from:newsletters@nautil.us" --limit 3
    python gmail_review_select.py select-approved --source nautilus --id SELECTED_ID --account-ref STABLE_ACCOUNT_LABEL --instruction-ref FOUNDER_INSTRUCTION --confirm-review-only

Use a distinct stable, non-secret account label per mailbox. The selector checks
one exact From mailbox and message identity before full retrieval and rechecks
both afterward. Attachments and HTML-only bodies are excluded. Email identities
are verified for Superhuman, The Code, and Nautilus. The Signal and Diary of a CEO
email identities stay disabled pending verification; explicit Diary documents
can use its exact official public host. Sender identity does not verify claims.

Ingest expects an explicit JSON object with source and approval, as emitted by
the selector. Source fields: kind, ref, source_id, title, creator, captured_at
with timezone, optional published_at, access_basis, content; email additionally
needs account_ref and message_id. Approval records matching source_ref,
scope review_only, and instruction_ref. Source instructions are untrusted data.

Extraction selects up to three exact short character spans and labels publisher
assertions UNRESOLVED. It is deterministic extractive screening, not model
reasoning or independent verification. Check context and practical relevance.
Manually analyzed envelopes remain supported by core_intake.submit_envelope.

    python learning_pipeline.py --store /path/to/private/reviews connect --packet HASH_A --packet HASH_B --relation analogy --hypothesis "Proposed connection" --challenge "What could invalidate it" --next-step "One measurable experiment" --reviewer Diamond --instruction-ref FOUNDER_INSTRUCTION --confirm-review-only
    python learning_pipeline.py --store /path/to/private/reviews feedback --target EXACT_HASH --decision needs_work --note "What to improve" --reviewer Diamond --instruction-ref FOUNDER_INSTRUCTION --confirm-review-only

Connections pin exact source hashes and revisions; newer evidence marks existing
connections stale. Repeated normalized bodies count as one evidence lineage.
Separate newsletter templates can still contain syndicated stories: independent
reporting requires reviewer assessment. No connection claims verification.
Feedback is immutable and target-specific; usefulness never promotes memory.
Status prints counts and hashes, never selected email text.

All records remain canonical=False, review_required=True. Replay validates the
available schema, identities, projects and complete available revision chains.
Serialized, create-only atomic publication requires filesystem hard-link support.
An abandoned lock fails closed. Hashes do not authenticate authorship or detect
deletion of a valid chain tail. Stored packets omit full source text; retain
private input snapshots if full evidence replay is needed. Private source/review
stores are excluded from Git and deliverables. On Windows, configure user-only
ACLs separately; POSIX modes do not configure Windows permissions.

This implementation has not been installed into the original Windows workspace
or its scheduler. It does not invoke the legacy sweep, whose separate Nautilus
path may still write opportunities. Session workers are session agents, not
installed background services. Website publishing and commercial changes remain
separate operations requiring a verified target, rollback and authorization.
