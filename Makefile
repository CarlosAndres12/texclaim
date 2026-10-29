.PHONY: install-global test lint eval

install-global:
	./scripts/install.sh

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

eval:
	@test -n "$(MODEL)" || { echo "usage: make eval MODEL=<model>"; exit 2; }
	python evals/run.py --model "$(MODEL)"
