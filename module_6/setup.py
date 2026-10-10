"""
`setup.py`
Makes the GradCafeAnalytics web package installable so its src/web/
packages import the same way everywhere: local runs, tests, and CI.
Install it editable from module_6 with `pip install -e .` (or
`uv pip install -e .`) after installing the relevant requirements.txt.

install_requires lists runtime dependencies as compatible version ranges.
requirements.txt pins every package to an exact version for reproducible
builds; the two are intentionally kept separate.
"""
from setuptools import find_packages, setup

setup(
    name="gradcafe-analytics",
    version="0.6.0",
    description=(
        "GradCafe admissions analytics served via Flask, with data "
        "ingestion decoupled through RabbitMQ and a Python worker."
    ),
    author="Cameron Ela",
    author_email="cela1@jh.edu",
    python_requires=">=3.11",
    package_dir={"": "src/web"},
    packages=find_packages(where="src/web"),
    py_modules=["paths", "run", "publisher"],
    package_data={
        "app": ["templates/*.html", "static/css/*.css"],
    },
    install_requires=[
        "Flask>=3.1,<4",
        "SQLAlchemy>=2.0,<2.1",
        "psycopg[binary]>=3.3,<4",
        "pika>=1.3,<2",
    ],
    extras_require={
        "dev": [
            "pytest>=8.3,<9",
            "pytest-cov>=6.0,<7",
            "pytest-randomly>=3.16,<4",
            "pylint>=4.1,<5",
            "Sphinx>=9.1,<10",
            "sphinx_rtd_theme>=3.1,<4",
            "beautifulsoup4>=4.15,<5",
        ],
    },
)
