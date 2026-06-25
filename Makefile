.PHONY: build verify example

build:
	uv run python site/build.py

verify:
	uv run python verify/qldpc_verify.py $(CODE)

example:
	uv run python verify/qldpc_verify.py examples/72-6-6.json
