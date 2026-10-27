"""Build a catalog from an independent snapshot and optional live NASA sources.

Orchestrates: config loading → seed loading → optional online fetch →
optional Wikipedia enrichment → validation → atomic write.
"""

import argparse
import copy
import json
import logging
from pathlib import Path

try:
    from .catalog import catalog_path, load_catalog, validate_catalog, write_catalog
    from .enrichment import enrich_wikipedia
    from .normalizers import positive_limit, identity_index, SourceError
    from .sources import JsonClient, fetch_exoplanets, fetch_small_bodies
except ImportError:
    # Running as script: python data/build_catalog.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from catalog import catalog_path, load_catalog, validate_catalog, write_catalog
    from enrichment import enrich_wikipedia
    from normalizers import positive_limit, identity_index, SourceError
    from sources import JsonClient, fetch_exoplanets, fetch_small_bodies

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = DATA_DIR / "catalog_config.json"
LOG = logging.getLogger(__name__)


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    http = config["http"]
    if not isinstance(http["retries"], int) or isinstance(http["retries"], bool) or http["retries"] < 0:
        raise ValueError("http.retries must be a nonnegative integer")
    if positive_limit(http["timeout_seconds"]) is None:
        raise ValueError("http.timeout_seconds must be positive")
    for name in ("exoplanets", "asteroids", "comets"):
        positive_limit(config["sources"][name]["limit"])
    return config


def build_enriched_catalog(
    config_path: Path = DEFAULT_CONFIG,
    output: Path = None,
    *,
    offline: bool = False,
    wikipedia: bool = False,
    limits: dict = None,
    client: JsonClient = None,
) -> list:
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    seed_path = (config_path.parent / config["seed"]).resolve()
    output = Path(output) if output is not None else catalog_path()
    if output.resolve() in (seed_path, config_path):
        raise ValueError("Output must not overwrite the input snapshot or configuration")
    if offline and wikipedia:
        raise ValueError("--offline cannot be combined with --wikipedia")

    seed = load_catalog(seed_path)
    items = copy.deepcopy(seed)

    if not offline:
        client = client or JsonClient(config["http"])
        identities = identity_index(seed)
        limits = limits or {}
        imported = []
        for source in ("exoplanets", "asteroids", "comets"):
            limit = positive_limit(limits.get(source, config["sources"][source]["limit"]))
            LOG.info("Loading %s (limit %s)", source, limit)
            if source == "exoplanets":
                imported.extend(fetch_exoplanets(client, config, identities, limit))
            else:
                imported.extend(fetch_small_bodies(
                    client, config, identities,
                    "asteroid" if source == "asteroids" else "comet", limit
                ))
        # Replace NASA/JPL-sourced objects with fresh data
        items = [item for item in items if not (
            (item.get("source") == "NASA Exoplanet Archive" and item["kind"] in {"star", "exoplanet"})
            or item["kind"] in {"asteroid", "comet"}
        )]
        items.extend(imported)
        if wikipedia:
            enrich_wikipedia(items, client, config)

    validate_catalog(items)
    write_catalog(output, items)
    LOG.info("Saved %s objects to %s (%s)", len(items), output, "offline snapshot" if offline else "NASA refreshed")
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="Defaults to ASTROVERSE_CATALOG_PATH or data/objects.json")
    parser.add_argument("--offline", action="store_true", help="Rebuild only from the independent input snapshot")
    parser.add_argument("--wikipedia", action="store_true", help="Refresh descriptions with explicit wikipedia_title")
    for source in ("exoplanets", "asteroids", "comets"):
        parser.add_argument(f"--{source}-limit", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    limits = {
        source: getattr(args, f"{source}_limit")
        for source in ("exoplanets", "asteroids", "comets")
        if getattr(args, f"{source}_limit") is not None
    }
    try:
        build_enriched_catalog(args.config, args.output, offline=args.offline, wikipedia=args.wikipedia, limits=limits)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        parser.exit(1, f"Catalog build failed; output was not replaced: {exc}\n")


if __name__ == "__main__":
    main()