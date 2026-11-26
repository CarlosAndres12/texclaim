.PHONY: install-global test lint eval web serve examples e2e

install-global:
	./scripts/install.sh

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

eval:
	@test -n "$(MODEL)" || { echo "usage: make eval MODEL=<model>"; exit 2; }
	python evals/run.py --model "$(MODEL)" $(ARGS)

web:
	cd web && npm install --no-audit --no-fund && npx tsc -b --noEmit && npx vite build

serve:
	texclaim serve --open

examples:
	python examples/build_examples.py

e2e:
	pytest -q tests/e2e
