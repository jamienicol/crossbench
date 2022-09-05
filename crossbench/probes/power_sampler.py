# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import csv
import logging
import subprocess
from pathlib import Path

from crossbench import helper, probes


class PowerSamplerProbe(probes.Probe):
  """
  Probe for chrome's power_sampler helper binary to collect MacOS specific
  battery and system usage metrics.
  """

  NAME = "powersampler"
  BATTERY_ONLY = True

  def __init__(self, power_sampler_bin_path=None):
    super().__init__()
    # TODO(fix)
    power_sampler_bin_path = Path.home(
    ) / "Documents/chrome/src/out/release/power_sampler"
    self._power_sampler_bin_path = power_sampler_bin_path
    assert self._power_sampler_bin_path.exists(), (
        "Could not find power_sampler binary at "
        f"'{self._power_sampler_bin_path}'")

  def pre_check(self, checklist):
    if not super().pre_check(checklist):
      return False
    if not helper.platform.is_battery_powered:
      logging.error("ERROR: Power Sampler only works on battery power!")
      return False
    # TODO() warn when external monitors are connected
    # TODO() warn about open terminals
    return True

  def is_compatible(self, browser):
    # For now only supported on MacOs
    return helper.platform.is_macos

  class Scope(probes.Probe.Scope):

    def __init__(self, probe, run):
      super().__init__(probe, run)
      self._bin_path = probe._power_sampler_bin_path
      self._active_user_process = None
      self._battery_process = None
      self._power_process = None
      self._battery_output = self.results_file.with_suffix(".battery.json")
      self._power_output = self.results_file.with_suffix(".power.json")

    def setup(self, run):
      self._active_user_process = helper.platform.popen(
          self._bin_path,
          "--no-samplers",
          "--simulate-user-active",
          stdout=subprocess.DEVNULL)
      assert self._active_user_process is not None, (
          "Could not start active user background sa")
      self._wait_for_battery_not_full(run)

    def start(self, run):
      assert self._active_user_process is not None
      self._battery_process = helper.platform.popen(
          self._bin_path,
          "--sample-on-notification",
          "--samplers=battery",
          f"--json-output-file={self._battery_output}",
          stdout=subprocess.DEVNULL)
      assert self._battery_process is not None, (
          "Could not start battery sampler")
      self._power_process = helper.platform.popen(
          self._bin_path,
          "--sample-interval=10",
          "--samplers=smc,user_idle_level,main_display",
          f"--json-output-file={self._power_output}",
          stdout=subprocess.DEVNULL)
      assert self._power_process is not None, "Could not start power sampler"

    def stop(self, run):
      self._power_process.terminate()
      self._battery_process.terminate()

    def tear_down(self, run):
      self._power_process.kill()
      self._battery_process.kill()
      self._active_user_process.terminate()
      return tuple({
          "power": self._power_output,
          "battery": self._battery_output
      }.values())

    def _wait_for_battery_not_full(self, run):
      """
      Empirical evidence has shown that right after a full battery charge, the
      current capacity stays equal to the maximum capacity for several minutes,
      despite the fact that power is definitely consumed. To ensure that power
      consumption estimates from battery level are meaningful, wait until the
      battery is no longer reporting being fully charged before crossbench.
      """

      logging.warning("POWER SAMPLER: Waiting for non-100% battery or "
                      "initial sample to synchronize")
      while True:
        assert helper.platform.is_battery_powered, (
            "Cannot wait for draining if power is connected.")

        power_sampler_output = helper.platform.sh_stdout(
            self._bin_path, "--sample-on-notification", "--samplers=battery",
            "--sample-count=1")

        for row in csv.DictReader(power_sampler_output.splitlines()):
          max_capacity = float(row["battery_max_capacity(Ah)"])
          current_capacity = float(row["battery_current_capacity(Ah)"])
          percent = 100 * current_capacity / max_capacity
          logging.info(f"POWER SAMPLER: Battery level is {percent:.2f}%")
          if max_capacity != current_capacity:
            return