Crossbench
==========

Crossbench is a cross-browser/cross-benchmark runner to extract performance
numbers.

This project uses [poetry](https://python-poetry.org/) deps and package scripts to setup the correct environment for testing and debugging.

```
pip3 install poetry
```

Example usage:

```
poetry run crossbench speedometer_2.0 \
    --browser=/path/to/chromium \
    --stories=VanillaJS.* \
    --probe=profiling \
    --probe=v8.log
```

Describe *all* subcommands with stories and all probes:
```
poetry run crossbench describe
```


Main Components
---------------
Browsers
:   Interface to start, interact and stop browsers.
    The main implementions use [selenium](https://www.selenium.dev/) for
    maximum system independence.

Probes
:   Probes define a way to extract arbitrary (performance) numbers from a
    host or running browser. This can reach from running simple JS-snippets to
    extract page-specific numbers to system-wide profiling.

Stories
:   Stories define sequences of browser interactions. This can be simply
    loading a URL and waiting for a given period of time, or in more complex
    scenarios, actively interact with a page and navigate multiple times.