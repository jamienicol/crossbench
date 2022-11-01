# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import csv
import logging
import pathlib
import subprocess
from typing import Optional, TYPE_CHECKING, Sequence, Tuple

if TYPE_CHECKING:
  import crossbench as cb
import crossbench.probes as probes

class PowerSamplerProbe(probes.Probe):
  """
  Probe for chrome's power_sampler helper binary to collect MacOS specific
  battery and system usage metrics.
  """

  NAME = "powersampler"
  BATTERY_ONLY = True
  SAMPLERS = ("smc", "user_idle_level", "main_display")

  @classmethod
  def config_parser(cls):
    parser = super().config_parser()
    parser.add_argument("bin_path", type=pathlib.Path)
    parser.add_argument("sampling_interval", type=int, default=10)
    parser.add_argument(
        "samplers",
        type=str,
        choices=cls.SAMPLERS,
        default=cls.SAMPLERS,
        is_list=True)
    return parser

  def __init__(self,
               bin_path: pathlib.Path,
               sampling_interval: int = 10,
               samplers: Sequence[str] = SAMPLERS):
    super().__init__()
    self._bin_path = bin_path
    assert self._bin_path.exists(), ("Could not find power_sampler binary at "
                                     f"'{self._bin_path}'")
    self._sampling_interval = sampling_interval
    assert sampling_interval > 0, (
        f"Invalid sampling_interval={sampling_interval}")
    assert 'battery' not in samplers
    self._samplers = tuple(samplers)

  @property
  def bin_path(self) -> pathlib.Path:
    return self._bin_path

  @property
  def sampling_interval(self) -> int:
    return self._sampling_interval

  @property
  def samplers(self) -> Tuple[str, ...]:
    return self._samplers

  def pre_check(self, env: cb.env.HostEnvironment):
    super().pre_check(env)
    if not self.browser_platform.is_battery_powered:
      env.handle_warning("Power Sampler only works on battery power!")
    # TODO() warn when external monitors are connected
    # TODO() warn about open terminals

  def is_compatible(self, browser: cb.browsers.Browser) -> bool:
    # For now only supported on MacOs
    return browser.platform.is_macos

  class Scope(probes.Probe.Scope):

    def __init__(self, probe: PowerSamplerProbe, run: cb.runner.Run):
      super().__init__(probe, run)
      self._bin_path = probe.bin_path
      self._active_user_process: Optional[subprocess.Popen] = None
      self._battery_process: Optional[subprocess.Popen] = None
      self._power_process: Optional[subprocess.Popen] = None
      self._battery_output = self.results_file.with_suffix(".battery.json")
      self._power_output = self.results_file.with_suffix(".power.json")

    def setup(self, run: cb.runner.Run):
      self._active_user_process = self.browser_platform.popen(
          self._bin_path,
          "--no-samplers",
          "--simulate-user-active",
          stdout=subprocess.DEVNULL)
      assert self._active_user_process is not None, (
          "Could not start active user background sa")
      self._wait_for_battery_not_full(run)

    def start(self, run: cb.runner.Run):
      assert self._active_user_process is not None
      self._battery_process = self.browser_platform.popen(
          self._bin_path,
          "--sample-on-notification",
          "--samplers=battery",
          f"--json-output-file={self._battery_output}",
          stdout=subprocess.DEVNULL)
      assert self._battery_process is not None, (
          "Could not start battery sampler")
      self._power_process = self.browser_platform.popen(
          self._bin_path,
          f"--sample-interval={self.probe.sampling_interval}",
          f"--samplers={','.join(self.probe.samplers)}",
          f"--json-output-file={self._power_output}",
          stdout=subprocess.DEVNULL)
      assert self._power_process is not None, "Could not start power sampler"

    def stop(self, run: cb.runner.Run):
      if self._power_process:
        self._power_process.terminate()
      if self._battery_process:
        self._battery_process.terminate()

    def tear_down(self, run: cb.runner.Run):
      if self._power_process:
        self._power_process.kill()
      if self._battery_process:
        self._battery_process.kill()
      if self._active_user_process:
        self._active_user_process.terminate()
      return tuple({
          "power": self._power_output,
          "battery": self._battery_output
      }.values())

    def _wait_for_battery_not_full(self, run: cb.runner.Run):
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
        assert self.browser_platform.is_battery_powered, (
            "Cannot wait for draining if power is connected.")

        power_sampler_output = self.browser_platform.sh_stdout(
            self._bin_path, "--sample-on-notification", "--samplers=battery",
            "--sample-count=1")

        for row in csv.DictReader(power_sampler_output.splitlines()):
          max_capacity = float(row["battery_max_capacity(Ah)"])
          current_capacity = float(row["battery_current_capacity(Ah)"])
          percent = 100 * current_capacity / max_capacity
          logging.info("POWER SAMPLER: Battery level is %.2f%%", percent)
          if max_capacity != current_capacity:
            return
