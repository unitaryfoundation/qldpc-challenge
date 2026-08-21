"""Build the OPTIONAL gf2_fast C++ accelerator (see gf2_fast.cpp).

The pure-Python engine remains the reference and fallback. CI builds this
trusted source best-effort (continue-on-error) so the gate's deep pass can use
it; a failed build restores the full Python search battery. Build locally with:

    make fast
"""
import os

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

_HERE = os.path.dirname(os.path.abspath(__file__))

setup(
    name="gf2_fast",
    version="0.1",
    description="Bit-packed GF(2) linear algebra for quantum code search",
    packages=[],           # extension only; keep setuptools away from the
    py_modules=[],         # repo's flat directory layout

    ext_modules=[
        Pybind11Extension(
            "gf2_fast",
            [os.path.join(_HERE, "gf2_fast.cpp")],
            cxx_std=17,
            extra_compile_args=["-O3"],
        ),
    ],
    cmdclass={"build_ext": build_ext},
)
