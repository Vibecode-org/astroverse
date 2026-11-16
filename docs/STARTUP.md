# SQLite: запуск и восстановление

`docker compose up --build -d` открывает рабочую SQLite без сети, seed и
`objects.json`. Runtime — `DiskCatalog`.

## Жизненный цикл и поставка

Default — `/app/data/runtime/catalog.sqlite`, named volume `catalog-runtime`.
Пустой volume получает проверенную поставку; существующая БД сохраняется при
restart/recreate/новом образе. `down` сохраняет volume; его удаление теряет patches.

`offline` — default; `published` требует существующий `ASTROVERSE_SECTOR_PATH`.
Явно выбранный отсутствующий путь, повреждение/несовместимость и режимы
`online/existing` дают ошибку без fallback. `ASTROVERSE_CATALOG_PATH` относится
к JSON tooling и не обновляет рабочую БД.

Docker проверяет готовые `data/bootstrap/catalog.sqlite`, `.manifest.json`,
`.sha256`, `release.json` из репозитория без JSON-каталога.
Pinned release фиксирует SHA исходного fixture и SQLite, semantic revision,
3471 карточку, schema2, `streaming/1`, `incremental_schema=1`, coordinates.
Это доверие к образу/репозиторию, не цифровая подпись.

Проверка воспроизводимости в тестовом окружении Python3.12/SQLite3.46.1:

```bash
make test-build
make unit ARGS='run --rm unit python -m data.bootstrap_catalog prepare data/catalog_seed.json /tmp/catalog.sqlite'
```

`prepare` проверяет закреплённый fixture и точные байты; смена release требует review.
Тёплый startup выполняет один полный integrity/FK check; холодный также
проверяет поставку и копию. Это O(N), без нормализации карточек.

## Backup и restore рабочей публикации

Сохранить весь bundle вне рабочего volume; каталог backups должен быть
доступен container uid10001. Имя bundle должно быть новым.

```bash
docker compose run --rm --no-deps -w /app -v "$PWD/backups:/backups" backend \
  python -m data.catalog_backup backup /app/data/runtime/catalog.sqlite /backups/working-01
docker compose run --rm --no-deps -w /app -v "$PWD/backups:/backups:ro" backend \
  python -m data.catalog_backup restore /backups/working-01 /app/data/runtime/catalog.sqlite --replace
```

Без `--replace` target должен отсутствовать: восстановить его до запуска API.
Bundle содержит побайтную SQLite и
`manifest.json` (`astroverse-backup/1`, ≤1MiB): checksum, compatibility и полную
metadata. Порядок, null, revisions, manifests, patches и v1/v2 сохраняются.
Внешние BSP/модели/конфиги сохранять с версией приложения отдельно.

Общий постоянный writer lock обеспечивает снимок одной ревизии. Backup
публикует каталог atomic rename; restore проверяет checksum/schema/capabilities,
metadata и integrity/FK в staging, делает fsync и atomic rename target.
До rename ошибка сохраняет прежнюю БД; после него ошибка fsync не отменяет
commit. Старые readers дочитывают прежний inode. Живые WAL/journal и in-place
SQL writers не поддерживаются. Lock-файлы не удалять. Process-crash атомарность
не доказывает durability при потере питания. Copy/hash/integrity — O(N); нужно
место под кандидата и старый inode, пока его держат readers.

## Переход прежней установки

До recreate остановить API/writers и сохранить последнюю SQLite из старого
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
проверяет копию до atomic rename, сохраняет байты и исходник. Удалённый слой
контейнера восстановить нельзя. Перед запуском убрать старый путь из `.env`/
overrides; выбрать `offline` либо `published` с новым persistent path.
Копию хранить до проверки. Если остался только JSON,
явно подготовить кандидат через `python -m backend.prepare_runtime SOURCE TARGET`;
startup его не ищет и не перестраивает несовместимую schema.

Обновления/лимиты — [SECTORS](SECTORS.md). Проверки, замеры и acceptance-команды —
[TEST_COVERAGE](TEST_COVERAGE.md), [tests/README](../tests/README.md).
