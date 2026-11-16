.DEFAULT_GOAL := help
SCENE ?= sectors
ARGS ?=
TEST_COMPOSE = docker compose -f tests/docker/compose.yml
UNIT = $(TEST_COMPOSE) -p astroverse-tests
SCENES = $(TEST_COMPOSE) -p astroverse-scene
ACCEPTANCE = $(TEST_COMPOSE) -p astroverse-acceptance --profile acceptance

.PHONY: help up down test-build test coverage unit scene scene-down acceptance-up acceptance-down acceptance
help:
	@printf '%s\n' 'make up / down                ordinary app :5173 (volume retained)' 'make test / coverage          isolated backend checks' 'make scene SCENE=sectors      HTTP fixture :5174' 'make scene SCENE=s100k        physical 100k :5174' 'make scene SCENE=legacy       legacy 100k :5174' 'make scene-down               stop test scene (volumes retained)' 'make acceptance-up / -down    offline runtime QA (volumes retained)' 'make unit ARGS="..."           raw test compose command' 'make acceptance ARGS="..."     raw isolated runtime compose command'
up:
	docker compose up --build -d --wait
down:
	docker compose down
test-build:
	$(UNIT) build unit
test: test-build
	$(UNIT) run --rm unit
coverage: test-build
	$(UNIT) run --rm unit sh -ec 'python -m pip install --target /tmp/coverage -r tests/requirements-coverage.txt; export PYTHONPATH=/tmp/coverage; python -m coverage run --branch --source=backend,data -m unittest discover -s tests -t .; python -m coverage report --fail-under=95; python -m coverage report --include=data/sectors.py --fail-under=100'
unit:
	$(UNIT) $(ARGS)
scene:
	@case "$(SCENE)" in sectors|s100k|legacy) ;; *) printf '%s\n' 'SCENE must be sectors, s100k or legacy'; exit 2;; esac
	$(SCENES) --profile '*' down --remove-orphans
	@if [ "$(SCENE)" = legacy ]; then $(SCENES) run --build --rm legacy sh -ec 'python -m data.gen_catalog_100k; python -m backend.prepare_runtime data/objects_100k.json data/runtime/stress100k.sqlite'; fi
	$(SCENES) --profile $(SCENE) up --build -d --wait
scene-down:
	$(SCENES) --profile '*' down --remove-orphans
acceptance-up:
	docker compose build backend
	@mkdir -p -m 777 "$${ASTROVERSE_BACKUP_DIR:-/tmp/astroverse-acceptance}"
	$(ACCEPTANCE) up -d --wait
acceptance-down:
	$(ACCEPTANCE) down
acceptance:
	$(ACCEPTANCE) $(ARGS)
