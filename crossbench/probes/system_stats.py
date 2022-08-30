# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import threading
import time

from crossbench import probes
from crossbench import helper


class SystemStatsProbe(probes.Probe):
  """
  General-purpose probe to periodically collect system-wide CPU and memory
  stats on unix systems.
  """
  NAME = 'system.stats'
  CMD = ("ps", "-a", "-e", "-o pcpu,pmem,args", "-r")

  def __init__(self, *args, interval=1, **kwargs):
    super().__init__(*args, **kwargs)
    self._interval = interval

  @property
  def interval(self):
    return self._interval

  def is_compatible(self, browser):
    return helper.platform.is_linux | helper.platform.is_macos

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
      data = helper.platform.sh_stdout(*cls.CMD)
      out_file = path / f"{time.time()}.txt"
      with out_file.open('w') as f:
        f.write(data)
      time.sleep(interval)

  class Scope(probes.Probe.Scope):

    def setup(self, run):
      self.results_file.mkdir()

    def start(self, run):
      self._event = threading.Event()
      self._poller = threading.Thread(
          target=SystemStatsProbe.poll,
          args=(self.probe.interval, self.results_file, self._event))
      self._poller.start()

    def stop(self, run):
      self._event.set()
