.PHONY: build verify example test test-fast fast ris

build:
	uv run python site/build.py

# Optional GPU RIS deep-search binary (verify/ris_gpu.cu); needs nvcc + an
# NVIDIA GPU. Driven by verify/ris_gpu.py, which CPU-verifies its output.
ris:
	mkdir -p build
	nvcc -O3 -arch=$(or $(RIS_ARCH),native) -o build/ris_gpu verify/ris_gpu.cu

# Optional C++ RIS accelerator (verify/gf2_fast.cpp); pure Python is the fallback.
fast:
	uv run --frozen --with pybind11 --with setuptools python verify/setup_gf2_fast.py \
	  build_ext --build-lib verify --build-temp build/gf2_fast

test:
	uv run --frozen python run_tests.py

test-fast:
	uv run --frozen python run_tests.py --skip-slow

verify:
	uv run python verify/qldpc_verify.py $(CODE)

example:
	uv run python verify/qldpc_verify.py codes/72-12-6.json
