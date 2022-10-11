# Crossbench

Crossbench is a cross-browser/cross-benchmark runner to extract performance
numbers.

## Setup:
This project uses [poetry](https://python-poetry.org/) deps and package scripts
to setup the correct environment for testing and debugging.

```
pip3 install poetry
```

Install the necessary dependencies from lock file via poetry

```
poetry install
```


## Basic usage:

```
poetry run crossbench speedometer_2.0 \
    --browser=/path/to/chromium \
    --stories=VanillaJS.* \
    --probe=profiling \
    --probe=v8.log
```

## Run Unit tests
```
poetry run python -m unittest
```

## Main Components

### Browsers
Crossbench supports running benchmarks on one or multiple browser configurations.
The main implementation uses selenium for maximum system independence.

You can specify a single browser with `--browser=<name>`

```
poetry run crossbench speedometer_2.0 \
    --browser=/path/to/chromium  \
    -- \
    --browser-flag-foo \
    --browser-flag-bar \
```

For more complex scenarios you can use a
[browser.config.hjson](browser.config.example.hjson) file.
It allows you to specify multiple browser and multiple flag configurations in
a single file and produce performance numbers with a single invocation.

```
poetry run crossbench speedometer_2.0 \
    --browser-config=config.hjson
```

The [example file](browser.config.example.hjson) lists and explains all
configuration details.

### Probes
Probes define a way to extract arbitrary (performance) numbers from a
host or running browser. This can reach from running simple JS-snippets to
extract page-specific numbers to system-wide profiling.

Multiple probes can be added with repeated `--probe=XXX` options.
You can use the `describe` subcommand to list all probes:

```
poetry run crossbench describe probes
```

### Benchmarks
Use the `describe` command to list all benchmark details:

```
poetry run crossbench describe benchmarks
```

### Stories
Stories define sequences of browser interactions. This can be simply
loading a URL and waiting for a given period of time, or in more complex
scenarios, actively interact with a page and navigate multiple times.

Use `--help` or describe to list all stories for a benchmark:

```
poetry run crossbench speedometer_2.0 --help
```

Use `--stories` to list individual comma-separated story names, or use a
regular expression as filter.

```
poetry run crossbench speedometer_2.0 \
    --browser=/path/to/chromium \
    --stories=VanillaJS.*
```
