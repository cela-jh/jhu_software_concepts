"""
`setup.py`
Makes GradCafeAnalytics an installable package, so its src/ packages
import the same way everywhere: local runs, tests, and CI. Install it
editable from module_5 with `pip install -e .` (or `uv pip install -e .`)
after installing requirements.txt.

install_requires lists the runtime libraries as compatible version
ranges, the abstract needs of the package. requirements.txt pins every
package to an exact version, the one concrete environment this project
is tested in, so the two are kept separate on purpose.
"""
from setuptools import find_packages, setup

setup(
    name="gradcafe-analytics",
    version="0.5.0",
    description=(
        "Scrapes GradCafe admissions results into PostgreSQL and serves "
        "an analysis webpage with SQL injection defenses."
    ),
    author="Cameron Ela",
    author_email="cela1@jh.edu",
    python_requires=">=3.12",
    # Code lives under src/; app, database, scraping, and llm_hosting are
    # packages, while paths and run are single top-level modules.
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    py_modules=["paths", "run"],
    # Non-Python files the code loads at runtime.
    package_data={
        "app": ["templates/*.html", "static/css/*.css"],
        "llm_hosting": ["canon_*.txt"],
    },
    install_requires=[
        "Flask>=3.1,<4",
        "SQLAlchemy>=2.0,<2.1",
        "psycopg[binary]>=3.3,<4",
        "selenium>=4.49,<5",
        "beautifulsoup4>=4.15,<5",
        "huggingface_hub>=2.0,<3",
        "llama-cpp-python>=0.3.35,<0.4",
    ],
    extras_require={
        "dev": [
            "pytest>=8.3,<9",
            "pytest-cov>=6.0,<7",
            "pytest-randomly>=3.16,<4",
            "pylint>=4.1,<5",
            "pydeps>=3.0,<4",
            "Sphinx>=9.1,<10",
            "sphinx_rtd_theme>=3.1,<4",
        ],
    },
)
