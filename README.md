# Crossbench

Crossbench is a cross-browser/cross-benchmark runner to extract performance
numbers.

Supported Browsers: Chrome/Chromium, Firefox, Safari and Edge.

Supported OS: macOS, linux and windows.

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
poetry run cb speedometer \
    --browser=/path/to/chromium \
    --stories=VanillaJS.* \
    --probe=profiling \
    --probe=v8.log
```

## Run Unit tests
```
poetry run pytest
```

Run detailed test coverage:
```
poetry run pytest --cov=crossbench --cov-report=html
```

Run [pytype](https://github.com/google/pytype) type checker:
```
poetry run pytype -j auto crossbench
```


## Main Components

### Browsers
Crossbench supports running benchmarks on one or multiple browser configurations.
The main implementation uses selenium for maximum system independence.

You can specify a browser with `--browser=<name>`. You can repeat the 
`--browser` argument to run multiple browser. If you need custom flags for
multiple browsers use `--browser-config`.

```
poetry run cb speedometer \
    --browser=/path/to/chromium  \
    -- -- \
        --browser-flag-foo \
        --browser-flag-bar
```

#### Browser Config File
For more complex scenarios you can use a
[browser.config.hjson](config/browser.config.example.hjson) file.
It allows you to specify multiple browser and multiple flag configurations in
a single file and produce performance numbers with a single invocation.

```
poetry run cb speedometer --browser-config=config.hjson
```

The [example file](config/browser.config.example.hjson) lists and explains all
configuration details.

### Probes
Probes define a way to extract arbitrary (performance) numbers from a
host or running browser. This can reach from running simple JS-snippets to
extract page-specific numbers to system-wide profiling.

Multiple probes can be added with repeated `--probe=XXX` options.
You can use the `describe` subcommand to list all probes:

```
poetry run cb describe probes
```

#### Inline Probe Config
Some probes can be configured, either with inline json when using `--probe` or
in a separate `--probe-config` hjson file. Use the `describe` command to list
all options.

```
poetry run cb describe probes v8.log
poetry run cb speedometer --probe='v8.log{prof:true}'
```

#### Probe Config File
For complex probe setups you can use `--probe-config=<file>`.
The [example file](config/probe.config.example.hjson) lists and explains all
configuration details. For the specific probe configuration properties consult
the `describe` command.

### Benchmarks
Use the `describe` command to list all benchmark details:

```
poetry run cb describe benchmarks
```

### Stories
Stories define sequences of browser interactions. This can be simply
loading a URL and waiting for a given period of time, or in more complex
scenarios, actively interact with a page and navigate multiple times.

Use `--help` or describe to list all stories for a benchmark:

```
poetry run cb speedometer --help
```

Use `--stories` to list individual comma-separated story names, or use a
regular expression as filter.

```
poetry run cb speedometer \
    --browser=/path/to/chromium \
    --stories=VanillaJS.*
```
