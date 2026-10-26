# HatsRx campaign links — founder review

The offline utility creates UTM links for four existing products using their actual Rx identifiers. It makes no network calls, writes no files, and sends or publishes nothing. Product artwork, prices, membership and commerce remain untouched.

```bash
python growth_links.py list
python growth_links.py link --product beautiful-mind --source instagram --medium organic_social --campaign founder-review --content existing-art-a
```

Choose a listed product key or its exact Rx identifier. Source, medium and campaign are required; content is optional. Output is JSON with product name, Rx identifier and URL. Only the official `hatsrx.com` and `www.hatsrx.com` destinations are accepted; arbitrary subdomains, lookalikes, credentials, ports and nonproduct paths are rejected. Existing UTM tags are replaced and query values are encoded.

For a small approved experiment, select one to three existing hats and approved creative assets. Compare tagged direct-product traffic with a comparable home-page destination in existing analytics. Keep the channel, offer, time window and creative comparable. Record product visits, add-to-cart, checkout starts and purchases; calculate rates only when their denominators and attribution are available. Low traffic or missing attribution is inconclusive. This tool does not install analytics or collect clicks, and no performance results exist yet.

Public evidence was retrieved on **October 25, 2026** through indexed website text. Crawl ages ranged from today to six days; records remain provisional, noncanonical research in `hatsrx_growth_review.json`. Founder review should resolve whether limited-quantity claims apply to particular designs alongside made-to-order production. White/U selection is an experiment hypothesis, not a verified checkout defect. Older indexed category prices, memberships and shipping terms were excluded from current defect findings.

Sources: [About](https://www.hatsrx.com/blank), [home](https://www.hatsrx.com/), [Beautiful Mind](https://www.hatsrx.com/product-page/beautiful-mind-snapback-hat), [Sea Heart](https://www.hatsrx.com/product-page/sea-heart-snapback-hat), [p.s. I Love You](https://www.hatsrx.com/product-page/p-s-i-love-you-snapback), [Crown State](https://www.hatsrx.com/product-page/crown-state-snapback-classic). Exact observed Rx identifiers, URLs and crawl ages are recorded in the JSON artifact.

Validation: `python -m unittest -v test_growth_links`.
