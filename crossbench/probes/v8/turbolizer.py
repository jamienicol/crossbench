# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

import crossbench
from crossbench.probes import base
from crossbench import helper
from crossbench.probes.results import ProbeResult

#TODO: fix imports
cb = crossbench

if TYPE_CHECKING:
  import crossbench.runner


class V8TurbolizerProbe(base.Probe):
  """
  Chromium-only Probe for extracting detailed turbofan graphs.
  Note: This probe can have significant overhead.
  Tool: https://v8.github.io/tools/head/turbolizer/index.html
  """
  NAME = "v8.turbolizer"

  def is_compatible(self, browser):
    return isinstance(browser, cb.browsers.Chromium)

  def attach(self, browser):
    super().attach(browser)
    browser.flags.set("--no-sandbox")
    browser.js_flags.set("--trace-turbo")

  class Scope(base.Probe.Scope):

    @property
    def results_dir(self):
      # Put v8.turbolizer files into separate dirs in case we have
      # multiple isolates
      turbolizer_log_dir = super().results_file
      turbolizer_log_dir.mkdir(exist_ok=True)
      return turbolizer_log_dir

    def setup(self, run):
      run.extra_js_flags["--trace-turbo-path"] = str(self.results_dir)
      run.extra_js_flags["--trace-turbo-cfg-file"] = str(self.results_dir /
                                                         "cfg.graph")

    def start(self, run):
      pass

    def stop(self, run):
      pass

    def tear_down(self, run) -> ProbeResult:
      log_dir = self.results_file.parent
      log_files = helper.sort_by_file_size(log_dir.glob("*"))
      return ProbeResult(file=tuple(log_files))
