# FRINXio-code2flow

This project is forked from [code2flow](https://github.com/scottrogowski/code2flow), which is a tool to generate call graphs for dynamic programming language with following algorithm:

1. Translate your source files into ASTs.
2. Find all function definitions.
3. Determine where those functions are called.
4. Connect the dots.

The purpose of this fork is to provide a command-line tool to find workflow tasks which call each other and output it in JSON format.

## How-tos

### Installation

Clone this repository and install `frinxio-code2flow`:

```bash
pip install .
```

### Usage

Run a script for a single file / directory:

```bash
frinxio-code2flow worker.py
```

Run a script for a multiple files / directories:

```bash
frinxio-code2flow /src/workers worker.py
```

See all command-line options by running `frinxio-code2flow --help`:

```bash
usage: frinxio-code2flow [-h] [--quiet] [--skip-parse-errors] paths [paths ...]

CMD tool to find workflow tasks which call each other.

positional arguments:
  paths                Files or directories to search in.

options:
  -h, --help           show this help message and exit
  --quiet, -q          Supress INFO logging.
  --skip-parse-errors  Skip files that the language parser fails on.
```

