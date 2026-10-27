"""Wikipedia enrichment for catalog objects."""

import logging
import urllib.parse
from typing import Any, Dict, List


def enrich_wikipedia(
    items: List[Dict[str, Any]],
    client: Any,
    config: Dict[str, Any],
    # Injected dependencies:
    SourceError=Exception,
) -> None:
    """Enrich object descriptions from Wikipedia.

    Only objects with explicit `wikipedia_title` are enriched to avoid
    ambiguous lookups and unbounded requests.
    """
    LOG = logging.getLogger(__name__)
    for item in items:
        title = item.get("wikipedia_title")
        if not title:
            continue
        url = config["sources"]["wikipedia"]["url"] + urllib.parse.quote(title, safe="")
        try:
            response = client.get(url)
            if not isinstance(response, dict) or response.get("type") == "disambiguation":
                raise SourceError("Ambiguous or malformed Wikipedia summary")
            extract = response.get("extract")
            if not isinstance(extract, str) or not extract.strip():
                raise SourceError("Empty Wikipedia summary")
            item["description"] = extract.strip()
            item["description_source"] = url
        except SourceError as exc:
            LOG.warning("Wikipedia enrichment skipped for %s: %s", item["id"], exc)
