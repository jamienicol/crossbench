# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from pathlib import Path

from crossbench import probes
from crossbench import runner

from crossbench.helper import platform


class V8RCSProbe(probes.Probe):
  """
  Chromium-only Probe to extract runtime-call-stats data that can be used by
  to analyze precise counters and time spent in various VM components in V8:
  https://v8.github.io/tools/head/callstats.html
  """
  NAME = "v8.rcs"

  def is_compatible(self, browser):
    return browser.type == "chrome"

  def attach(self, browser):
    super().attach(browser)
    browser.js_flags.update(("--runtime-call-stats", "--allow-natives-syntax"))

  @property
  def results_file_name(self):
    return f"{self.name}.txt"

  class Scope(probes.Probe.Scope):
    def setup(self, run):
      pass

    def start(self, run):
      pass

    def stop(self, run):
      with run.actions("Extract RCS") as actions:
        self._rcs_table = actions.js("return %GetAndResetRuntimeCallStats();")

    def tear_down(self, run):
      assert self._rcs_table is not None and len(self._rcs_table) > 0, (
          "Chrome didn't produce any RCS data. "
          "Please make sure to enable the compile-time flag.")
      rcs_file = run.get_probe_results_file(self.probe)
      with rcs_file.open("a") as f:
        f.write(self._rcs_table)
      return rcs_file

  def merge_repetitions(self, group: runner.RepetitionsRunGroup):
    merged_result_path = group.get_probe_results_file(self)
    result_files = (Path(run.results[self]) for run in group.runs)
    return platform.concat_files(inputs=result_files, output=merged_result_path)

  def merge_stories(self, group: runner.StoriesRunGroup):
    merged_result_path = group.get_probe_results_file(self)
    with merged_result_path.open('w') as merged_file:
      for repetition_group in group.repetitions_groups:
        merged_iterations_file = Path(repetition_group.results[self])
        merged_file.write(f"\n== Page: {repetition_group.story.name}\n")
        with merged_iterations_file.open() as f:
          merged_file.write(f.read())
    return merged_result_path
