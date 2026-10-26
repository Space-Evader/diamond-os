"""Create campaign links for existing HatsRx products, without network or writes.

These tags identify traffic in analytics that already supports UTM parameters;
this tool does not install analytics, track clicks, or report sales.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    rx_id: str
    url: str


# Exact identifiers and URLs observed on the public product pages on 2026-10-25.
# Indexed observations remain provisional; see hatsrx_growth_review.json.
PRODUCTS = (
    Product("beautiful-mind", "Beautiful Mind™ Snapback Hat", "HXRX-BEAUTYMND-ARTCAP",
            "https://www.hatsrx.com/product-page/beautiful-mind-snapback-hat"),
    Product("sea-heart", "Sea Heart™ Snapback Hat", "HXRX-SEAHEART-ARTCAP",
            "https://www.hatsrx.com/product-page/sea-heart-snapback-hat"),
    Product("psily", "p.s. I Love You™ Snapback", "HXRX-PSILY-LOVE",
            "https://www.hatsrx.com/product-page/p-s-i-love-you-snapback"),
    Product("crown-state", "Crown State™ Snapback Classic", "HXRX-CROWNSTATE-CORE",
            "https://www.hatsrx.com/product-page/crown-state-snapback-classic"),
)
ALLOWED_HOSTS = frozenset({"hatsrx.com", "www.hatsrx.com"})
PRODUCT_PATH = re.compile(r"/product-page/[a-z0-9]+(?:-[a-z0-9]+)*/?\Z")


def validate_product_url(url: str) -> None:
    """Accept the official apex/www host and a plain product-page path only."""
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("Product URL must be a plain HTTPS HatsRx product URL")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ValueError("Invalid product URL") from exc
    if (parts.scheme != "https" or parts.netloc.lower() not in ALLOWED_HOSTS
            or not PRODUCT_PATH.fullmatch(parts.path) or parts.fragment):
        raise ValueError("Product URL must use https://hatsrx.com or https://www.hatsrx.com and /product-page/<slug>")


def _utm_value(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} cannot contain control characters")
    value = value.strip()
    if not value or len(value) > 200:
        raise ValueError(f"{name} must contain 1–200 characters")
    return value


def _tag_url(url: str, source: str, medium: str, campaign: str, content: str | None = None) -> str:
    validate_product_url(url)
    parts = urlsplit(url)
    # Preserve unrelated query values and replace all old UTM tags, including
    # duplicate/mixed-case ones, so old campaign attribution cannot leak through.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    for name, value in (("utm_source", source), ("utm_medium", medium), ("utm_campaign", campaign)):
        query.append((name, _utm_value(value, name)))
    if content is not None:
        query.append(("utm_content", _utm_value(content, "utm_content")))
    return urlunsplit(("https", parts.netloc.lower(), parts.path, urlencode(query), ""))


def get_product(identifier: str) -> Product:
    """Resolve a registry key or the exact stable Rx identifier."""
    for product in PRODUCTS:
        if identifier in (product.key, product.rx_id):
            return product
    raise ValueError("Unknown product; run 'python growth_links.py list' for verified choices")


def generate_link(product: str, source: str, medium: str, campaign: str, content: str | None = None) -> dict[str, str]:
    entry = get_product(product)
    return {"product": entry.name, "rx_id": entry.rx_id,
            "url": _tag_url(entry.url, source, medium, campaign, content)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List existing products and stable Rx identifiers")
    link = commands.add_parser("link", help="Generate a tagged product URL; does not send or publish it")
    link.add_argument("--product", required=True, help="Registry key or exact Rx identifier")
    link.add_argument("--source", required=True, help="Traffic source, such as instagram")
    link.add_argument("--medium", required=True, help="Traffic medium, such as organic_social")
    link.add_argument("--campaign", required=True, help="Campaign name chosen by the founders")
    link.add_argument("--content", help="Optional label for comparing existing creative variants")
    args = parser.parse_args(argv)
    if args.command == "list":
        result = [{"key": p.key, "product": p.name, "rx_id": p.rx_id, "url": p.url} for p in PRODUCTS]
    else:
        try:
            result = generate_link(args.product, args.source, args.medium, args.campaign, args.content)
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
