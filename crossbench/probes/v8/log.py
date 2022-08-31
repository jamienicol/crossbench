# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from crossbench import browsers, flags, helper, probes


class V8LogProbe(probes.Probe):
  """
  Chromium-only probe that produces a v8.log file with detailed internal V8
  performance and logging information.
  This file can be used by tools hosted on <http://v8.dev/tools>.
  """
  NAME = "v8.log"

  @classmethod
  def all(cls):
    pass

  def __init__(self, file="v8.log", log_all=True, prof=None, js_flags=None):
    super().__init__()
    self._js_flags = flags.JSFlags()
    self._js_flags.set("--log")
    enabled = False
    if log_all:
      self._js_flags.set("--log-all")
      enabled = True
    enabled |= self._enable_js_flag('prof', prof)
    assert enabled, "V8LogProbe has no effect"

  def _enable_js_flag(self, flag_name, value):
    if value is None:
      return False
    if value:
      self._js_flags.set(f"--{flag_name}")
    else:
      self._js_flags.set(f"--no-{flag_name}")
    return value

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
      log_dir.mkdir()
      return log_dir / self.probe.results_file_name

    def setup(self, run):
      run.extra_js_flags["--logfile"] = str(self.results_file)

    def start(self, run):
      pass

    def stop(self, run):
      pass

    def tear_down(self, run):
      log_dir = self.results_file.parent
      log_files = helper.sort_by_file_size(log_dir.glob("*-v8.log"))
      # Sort by file size, biggest first
      return tuple(str(f) for f in log_files)
