# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from pathlib import Path

import crossbench
from crossbench import helper, probes


class V8BuiltinsPGOProbe(probes.Probe):
  """
  Chromium-only Probe to extract V8 builtins PGO data.
  The resulting data is used to optimize Torque and CSA builtins.
  """
  NAME = "v8.builtins.pgo"

  def is_compatible(self, browser):
    return browser.type == "chrome"

  def attach(self, browser: crossbench.browsers.Chrome):
    super().attach(browser)
    browser.js_flags.set('--allow-natives-syntax')

  class Scope(probes.Probe.Scope):

    def __init__(self, *args, **kwargs):
      super().__init__(*args, *kwargs)
      self._pgo_counters = None

    def setup(self, run):
      pass

    def start(self, run):
      pass

    def stop(self, run):
      with run.actions("Extract Builtins PGO DATA") as actions:
        self._pgo_counters = actions.js(
            "return %GetAndResetTurboProfilingData();")

    def tear_down(self, run):
      assert self._pgo_counters is not None and len(self._pgo_counters) > 0, (
          "Chrome didn't produce any V8 builtins PGO data. "
          "Please make sure to set the v8_enable_builtins_profiling=true "
          "gn args.")
      pgo_file = run.get_probe_results_file(self.probe)
      with pgo_file.open("a") as f:
        f.write(self._pgo_counters)
      return pgo_file

  def merge_repetitions(self, group:  crossbench.runner.RepetitionsRunGroup):
    merged_result_path = group.get_probe_results_file(self)
    result_files = (Path(run.results[self]) for run in group.runs)
    return helper.platform.concat_files(inputs=result_files,
                                        output=merged_result_path)

  def merge_stories(self, group: crossbench.runner.StoriesRunGroup):
    merged_result_path = group.get_probe_results_file(self)
    result_files = (
        Path(group.results[self]) for group in group.repetitions_groups)
    return helper.platform.concat_files(inputs=result_files,
                                        output=merged_result_path)
