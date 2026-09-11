"""Build instrumentation without editing the verifier's native source."""

from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

setup(
    name="qldpc-distance-benchmark",
    packages=[],
    py_modules=[],
    ext_modules=[
        Pybind11Extension(
            "benchmark_native",
            [str(Path(__file__).with_name("native.cpp"))],
            cxx_std=17,
            extra_compile_args=["-O3"],
        )
    ],
    cmdclass={"build_ext": build_ext},
)
