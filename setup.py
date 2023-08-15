from setuptools import setup

setup(
    name="frinxio-code2flow",
    version="0.1.0",
    url="https://github.com/FRINXio/code2flow.git",
    license="MIT",
    description="CMD tool to find workflow tasks which call each other.",
    long_description=open("README.md", encoding="utf-8").read(),
    entry_points={
        "console_scripts": ["frinxio-code2flow=code2flow.engine:main"],
    },
    packages=["code2flow"],
)
