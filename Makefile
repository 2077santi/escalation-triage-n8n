PY ?= python

build:
	$(PY) workflow/build.py

test: build
	node --test workflow/*.test.js

eval-mock:
	$(PY) eval/evaluate.py --mock

eval:
	$(PY) eval/evaluate.py

.PHONY: build test eval-mock eval
