"""Prepare a deliberately different bootstrap for isolated image-upgrade QA.

This is a derived SQLite test fixture, never a production release or a new
scientific source. Both variants must preserve the same external model assets.
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    from data.bootstrap_catalog import DEFAULT_BOOTSTRAP_PATH, sha256_file
    from data.incremental_catalog import publish_changes
    from data.runtime_catalog import DiskCatalog
    root = args.directory
    root.mkdir(parents=True, exist_ok=False)
    path = root/'catalog.sqlite'
    shutil.copyfile(DEFAULT_BOOTSTRAP_PATH, path)
    with DiskCatalog(path).snapshot() as snapshot:
        sun = snapshot.object('sun')
        revision = snapshot.metadata['catalog_revision']
    sun['description'] = 'Isolated delivery variant fixture; never the working publication'
    metadata = publish_changes(path, expected_revision=revision, upserts=[sun])
    digest = sha256_file(path)
    fields = ('catalog_revision','object_count','coordinates','schema_version','builder','incremental_schema')
    manifest = dict(format='astroverse-bootstrap/1',sha256=digest,
        source='catalog.sqlite', source_sha256=sha256_file(DEFAULT_BOOTSTRAP_PATH),
        sqlite_version=sqlite3.sqlite_version,
        capabilities={'incremental_schema':metadata.get('incremental_schema')},
        **{key:metadata[key] for key in fields})
    release = dict(format='astroverse-release/1',artifact_version='delivery-test-variant',
        artifact_sha256=digest, expected_metadata={key:metadata[key] for key in fields},
        **{key:manifest[key] for key in ('source','source_sha256','sqlite_version')},
        provenance='Derived SQLite fixture for isolated acceptance only',
        preparation='python -m tests.prepare_delivery_variant DIRECTORY')
    for name, value in [('catalog.sqlite.manifest.json',manifest),('release.json',release)]:
        (root/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    (root/'catalog.sqlite.sha256').write_text(digest+'\n')
    print(json.dumps(dict(sha256=digest,revision=metadata['catalog_revision'])))


if __name__ == '__main__':
    main()
