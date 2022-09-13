# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import threading
import time

import crossbench as cb
import crossbench.probes as probes


class SystemStatsProbe(probes.Probe):
  """
  General-purpose probe to periodically collect system-wide CPU and memory
  stats on unix systems.
  """
  NAME = "system.stats"
  CMD = ("ps", "-a", "-e", "-o", "pcpu,pmem,args", "-r")

  def __init__(self, *args, interval=1, **kwargs):
    super().__init__(*args, **kwargs)
    self._interval = interval

  @property
  def interval(self):
    return self._interval

  def is_compatible(self, browser):
    return not browser.platform.is_remote and (browser.platform.is_linux or
                                               browser.platform.is_macos)

  def pre_check(self, checklist):
    if not super().pre_check(checklist):
      return False
    if checklist.runner.repetitions > 1:
      return checklist.warn(
          f"Probe={self.NAME} cannot merge data over multiple "
          f"repetitions={checklist.runner.repetitions}. Continue?")
    return True

  @classmethod
  def poll(cls, interval, path, event):
    while not event.is_set():
      # TODO(cbruni): support remote platform
      data = cb.helper.platform.sh_stdout(*cls.CMD)
      out_file = path / f"{time.time()}.txt"
      with out_file.open("w") as f:
        f.write(data)
      time.sleep(interval)

  class Scope(probes.Probe.Scope):

    def setup(self, run):
      self.results_file.mkdir()

    def start(self, run):
      self._event = threading.Event()
      assert self.browser_platform == cb.helper.platform, (
          "Remote platforms are not supported yet")
      self._poller = threading.Thread(
          target=SystemStatsProbe.poll,
          args=(self.probe.interval, self.results_file, self._event))
      self._poller.start()

    def stop(self, run):
      self._event.set()

    def tear_down(self, run: cb.runner.Run):
      return self.results_file
