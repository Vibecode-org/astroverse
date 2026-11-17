# SQLite: запуск и восстановление

`docker compose up --build -d` открывает рабочую SQLite (`DiskCatalog`)
без сети, seed и `objects.json`.

## Жизненный цикл и поставка

Default: `/app/data/runtime/catalog.sqlite`, named volume `catalog-runtime`.
Пустой volume получает проверенную поставку; существующая БД сохраняется
при restart/recreate/новом образе. `down` сохраняет volume; его удаление теряет patches.

`offline` — default; `published` требует существующий `ASTROVERSE_SECTOR_PATH`.
Отсутствующий явно заданный путь, повреждение/несовместимость и режимы
`online/existing` дают ошибку без fallback. `ASTROVERSE_CATALOG_PATH` —
JSON tooling, рабочую БД не обновляет.

Docker без JSON-каталога проверяет готовые `data/bootstrap/catalog.sqlite`,
`.manifest.json`, `.sha256`, `release.json` из репозитория.
Pinned release фиксирует SHA исходного fixture и SQLite, semantic revision,
3471 карточку, schema2, `streaming/1`, `incremental_schema=1`, coordinates.
Доверие к образу/репозиторию, не цифровая подпись.

Воспроизводимость (тестовое окружение Python3.12/SQLite3.46.1):

```bash
make test-build
make unit ARGS='run --rm unit python -m data.bootstrap_catalog prepare data/catalog_seed.json /tmp/catalog.sqlite'
```

`prepare`: проверка закреплённого fixture и точных байтов; смена release требует review.
Тёплый startup выполняет один полный integrity/FK check; холодный также
проверяет поставку и копию. Это O(N), без нормализации карточек.

## Backup и restore рабочей публикации

Весь bundle хранить вне рабочего volume; backups доступен container uid10001.
Имя bundle — новое.

```bash
docker compose run --rm --no-deps -w /app -v "$PWD/backups:/backups" backend \
  python -m data.catalog_backup backup /app/data/runtime/catalog.sqlite /backups/working-01
docker compose run --rm --no-deps -w /app -v "$PWD/backups:/backups:ro" backend \
  python -m data.catalog_backup restore /backups/working-01 /app/data/runtime/catalog.sqlite --replace
```

Без `--replace` target должен отсутствовать; восстановить до запуска API.
Bundle: побайтная SQLite и `manifest.json` (`astroverse-backup/1`, ≤1MiB)
с checksum, compatibility и полной metadata. Порядок, null, revisions, manifests, patches
и v1/v2 сохраняются.
Внешние BSP/модели/конфиги и версию приложения сохранять отдельно.

Общий постоянный writer lock фиксирует снимок одной ревизии. Backup
публикует каталог atomic rename; restore проверяет checksum/schema/capabilities,
metadata и integrity/FK в staging, затем fsync и atomic rename target.
До rename ошибка сохраняет прежнюю БД; после него ошибка fsync commit не отменяет. Старые
readers дочитывают прежний inode. Живые WAL/journal и in-place
SQL writers не поддерживаются. Lock-файлы не удалять. Process-crash атомарность
не доказывает power-loss durability. Copy/hash/integrity — O(N); нужно
место под кандидата и старый inode, пока его держат readers.

## Переход прежней установки

До recreate остановить API/writers, сохранить последнюю SQLite старого
контейнера (`objects.runtime.sqlite` либо фактический `ASTROVERSE_SECTOR_PATH`):

```bash
docker compose stop backend frontend
docker compose cp backend:/app/data/objects.runtime.sqlite ./data/previous.runtime.sqlite
docker compose build backend
docker compose run --rm --no-deps -w /app \
  -v "$PWD/data/previous.runtime.sqlite:/tmp/previous.sqlite:ro" backend \
  python -m data.bootstrap_catalog migrate /tmp/previous.sqlite /app/data/runtime/catalog.sqlite
```

`migrate` требует пустой target и совместимую standalone DELETE-journal БД;
проверяет копию до atomic rename; байты и исходник сохраняются. Удалённый слой
контейнера восстановить нельзя. Перед запуском убрать старый путь из `.env` /overrides;
выбрать `offline` либо `published` с новым persistent path.
Копию хранить до проверки. Если остался только JSON —
явно подготовить кандидат: `python -m backend.prepare_runtime SOURCE TARGET`;
startup его не ищет, несовместимую schema не перестраивает.

Обновления/лимиты — [SECTORS](SECTORS.md). Проверки, замеры и acceptance-команды —
[TEST_COVERAGE](TEST_COVERAGE.md), [tests/README](../tests/README.md).
