# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
from typing import Iterable, Optional

import crossbench as cb
import crossbench.probes as probes


class V8LogProbe(probes.Probe):
  """
  Chromium-only probe that produces a v8.log file with detailed internal V8
  performance and logging information.
  This file can be used by tools hosted on <http://v8.dev/tools>.
  """
  NAME = "v8.log"

  @classmethod
  def from_config(cls, config_data) -> V8LogProbe:
    log_all = config_data.get('log_all', True)
    prof = config_data.get('prof', False)
    js_flags = config_data.get('js_flags', [])
    return cls(log_all, prof, js_flags)

  def __init__(self,
               log_all: bool = True,
               prof: bool = False,
               js_flags: Optional[Iterable[str]] = None):
    super().__init__()
    self._js_flags = cb.flags.JSFlags()
    if log_all:
      self._js_flags.set("--log-all")
    if prof:
      self._js_flags.set("--prof")
    if js_flags:
      for flag in js_flags:
        if flag == "--prof" or flag.startswith("--log"):
          self._js_flags.set(flag)
        else:
          raise ValueError("None v8.log related flag detected: {flag}")
    assert len(self._js_flags) > 0, "V8LogProbe has no effect"
    self._js_flags.set("--log")

  def is_compatible(self, browser):
    return browser.type == "chrome"

  def attach(self, browser):
    super().attach(browser)
    browser.flags.set("--no-sandbox")
    browser.js_flags.update(self._js_flags)

  def pre_check(self, checklist):
    if not super().pre_check(checklist):
      return False
    if checklist.runner.repetitions > 1:
      return checklist.warn(
          f"Probe={self.NAME} cannot merge data over multiple "
          f"repetitions={checklist.runner.repetitions}. Continue?")
    return True

  class Scope(probes.Probe.Scope):

    @property
    def results_file(self):
      # Put v8.log files into separate dirs in case we have multiple isolates
      log_dir = super().results_file
      log_dir.mkdir(exist_ok=True)
      return log_dir / self.probe.results_file_name

    def setup(self, run):
      run.extra_js_flags["--logfile"] = str(self.results_file)

    def start(self, run):
      pass

    def stop(self, run):
      pass

    def tear_down(self, run):
      log_dir = self.results_file.parent
      log_files = cb.helper.sort_by_file_size(log_dir.glob("*-v8.log"))
      # Sort by file size, biggest first
      return tuple(str(f) for f in log_files)
