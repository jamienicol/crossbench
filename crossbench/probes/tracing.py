# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
import argparse
import enum
import pathlib

from typing import TYPE_CHECKING, List, Optional, Sequence, cast
from crossbench import cli_helper

from crossbench.browsers.chromium import Chromium
from crossbench.probes.probe import Probe, ProbeConfigParser
from crossbench.probes.results import ProbeResult

if TYPE_CHECKING:
  from crossbench.flags import ChromeFlags
  from crossbench.runner import Run
  from crossbench.browsers.browser import Browser


class RecordMode(enum.Enum):
  CONTINUOUSLY = "record-continuously"
  UNTIL_FULL = "record-until-full"
  AS_MUCH_AS_POSSIBLE = "record-as-much-as-possible"


class TracingProbe(Probe):
  """
  Chromium-only Probe to collect tracing / perfetto data that can be used by
  chrome://tracing or https://ui.perfetto.dev/.

  Currently WIP
  """
  NAME = "tracing"
  CHROMIUM_FLAGS = ("--enable-perfetto",)
  DEFAULT_CATEGORIES = (
      "toplevel",
      "v8",
      "v8.execute",
  )
  HELP_URL = "https://www.chromium.org/developers/how-tos/trace-event-profiling-tool/"

  @classmethod
  def config_parser(cls) -> ProbeConfigParser:
    parser = super().config_parser()
    parser.add_argument(
        "categories",
        is_list=True,
        default=cls.DEFAULT_CATEGORIES,
        type=str,
        help=("A list of trace categories to enable. "
              f"See chrome's {cls.HELP_URL} for more details"))
    parser.add_argument(
        "trace_config",
        type=cli_helper.parse_json_file_path,
        help=("Sets Chromium's --trace-config-file to the given json config."))
    parser.add_argument(
        "startup_duration",
        type=cli_helper.parse_positive_float,
        help="Stop recording tracing after a certain time")
    parser.add_argument(
        "record_mode",
        default=RecordMode.CONTINUOUSLY,
        type=RecordMode,
        help="Stop recording tracing after a certain time")
    return parser

  def __init__(self,
               categories: Optional[Sequence[str]] = None,
               trace_config: Optional[pathlib.Path] = None,
               startup_duration: float = 0,
               record_mode: RecordMode = RecordMode.CONTINUOUSLY,
               output_format: str = "json") -> None:
    super().__init__()
    self._trace_config = trace_config
    if self._trace_config:
      if categories and tuple(categories) != self.DEFAULT_CATEGORIES:
        raise argparse.ArgumentTypeError(
            "TracingProbe requires either a list of "
            "trace categories or a trace_config file.")
      self._categories = []
    else:
      self._categories = categories or self.DEFAULT_CATEGORIES

    self._startup_duration = startup_duration
    self._record_mode = record_mode
    self._format = output_format
    assert self._format in ("json", "proto"), (
        f"Invalid trace output output_format={self._format}")

  @property
  def results_file_name(self) -> str:
    return f"{self.name}.json"

  def is_compatible(self, browser: Browser) -> bool:
    return isinstance(browser, Chromium)

  def attach(self, browser: Chromium) -> None:
    flags: ChromeFlags = browser.flags
    flags.update(self.CHROMIUM_FLAGS)
    if self._trace_config:
      flags["--trace-config-file"] = str(self._trace_config)
    else:
      flags["--trace-startup-format"] = "json"
      if self._startup_duration:
        flags["--trace-startup-duration"] = str(self._startup_duration)
      flags["--trace-startup-record-mode"] = str(self._record_mode.value)
      flags["--trace-startup"] = ",".join(self._categories)
    super().attach(browser)

  class Scope(Probe.Scope):

    def setup(self, run: Run) -> None:
      run.extra_flags["--trace-startup-file"] = str(self.results_file)

    def start(self, run: Run) -> None:
      del run

    def stop(self, run: Run) -> None:
      del run

    def tear_down(self, run: Run) -> ProbeResult:
      return ProbeResult(json=(self.results_file,))
