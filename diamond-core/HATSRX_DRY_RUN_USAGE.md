# HatsRx offline campaign preflight

```sh
python -B diamond-core/campaign_dry_run.py --demo
python -B diamond-core/campaign_dry_run.py --input /private/campaign-plan.json
```

No network, Wix client, publication or commerce settings are involved. Output is
a local review report, not a published campaign. The four approved products,
stable Rx identifiers and official storefront URLs come directly from the
unchanged recovered `growth_links.PRODUCTS` registry observed October 25, 2026.
This checks registry consistency, not live availability, prices or analytics.

A plan has exactly `schema: diamond.hatsrx-dry-run/1` and `rows` (1–32 entries).
Each row requires `id`, `product` (registry key or exact Rx ID), `rx_id`, `source`,
`medium`, and `campaign`. Optional fields are `content` and `destination`.
Use `growth_links.py list` for approved choices. The default destination is the
registry URL. A supplied destination must use an exact official HTTPS host and
the same registered product path. Credentials, ports, fragments, lookalike hosts,
unregistered paths and input query parameters are rejected. Existing UTM tags
must be removed explicitly; the dry-run never silently replaces attribution.

The existing generator handles URL encoding. Preflight verifies that every
generated parameter decodes back to its original trimmed value, without creating
extra query keys. Explicit null/empty content labels and control characters are
rejected. Duplicate row IDs invalidate both rows. Attribution duplicates for the
same Rx ID also invalidate both rows, including product aliases and Unicode/case
variants. Use distinct `content` labels for intentional creative comparisons.
The same campaign across different products is valid.

Rows with errors have no candidate URL in the report. `ready_for_review` is true
only if every row passes; it never grants permission to publish. CLI exit status
is 0 for an entirely valid plan, 1 for blocked rows, and 2 for an invalid plan or
input. Failed rows do not prevent the rest from being inspected. The command
writes no files; save reports only in an appropriate private workspace if needed.

The demo uses illustrative campaign labels, not a commercial launch. Keep actual
campaign plans and outcome feedback outside Git. Use the existing feedback API
to record measured preflight results against the supporting review packet; a
useful check is not evidence of increased revenue or conversion.
