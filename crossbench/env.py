# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import datetime as dt
import enum
import logging
import os
import shutil
import psutil
from typing import TYPE_CHECKING, List, Optional, Union

from dataclasses import dataclass

import crossbench as cb
if TYPE_CHECKING:
  from crossbench import runner
  from crossbench import probes

from crossbench import helper

@dataclass(frozen=True)
class HostEnvironmentConfig:
  Ignore = None

  disk_min_free_space_gib: Optional[float] = Ignore
  power_use_battery: Optional[bool] = Ignore
  screen_brightness_percent: Optional[int] = Ignore
  cpu_max_usage_percent: Optional[int] = Ignore
  cpu_min_relative_speed: Optional[float] = Ignore
  system_allow_antivirus: Optional[bool] = Ignore
  browser_allow_existing_process: Optional[bool] = Ignore
  browser_is_headless: Optional[bool] = Ignore
  require_probes: Optional[bool] = Ignore


class ValidationMode(enum.Enum):
  PROMPT = "prompt"
  WARN = "warn"
  THROW = "throw"
  SKIP = "skip"


class ValidationError(Exception):
  pass


class HostEnvironment:
  """
  HostEnvironment can check and enforce certain settings on a host
  where we run benchmarks.

  Modes:
    skip:     Do not perform any checks
    warn:     Only warn about mismatching host conditions
    enforce:  Tries to auto-enforce conditions and warns about others.
    prompt:   Interactive mode to skip over certain conditions
    fail:     Fast-fail on mismatch
  """

  def __init__(self,
               runner: cb.runner.Runner,
               config: Optional[HostEnvironmentConfig] = None,
               validation_mode: ValidationMode = ValidationMode.THROW):
    self._wait_until = dt.datetime.now()
    self._config = config or HostEnvironmentConfig()
    self._runner = runner
    self._platform = runner.platform
    self._validation_mode = validation_mode

  @property
  def runner(self) -> runner.Runner:
    return self._runner

  @property
  def config(self) -> HostEnvironmentConfig:
    return self._config

  def _add_min_delay(self, seconds: float):
    end_time = dt.datetime.now() + dt.timedelta(seconds=seconds)
    if end_time > self._wait_until:
      self._wait_until = end_time

  def _wait_min_time(self):
    delta = self._wait_until - dt.datetime.now()
    if delta > dt.timedelta(0):
      self._platform.sleep(delta)

  def handle_warning(self, message: str):
    """Process a warning, depending on the requested mode, this will
    - throw an error,
    - log a warning,
    - prompts for continue [Yn], or
    - skips (and just debug logs) a warning.
    If returned True (in the prompt mode) the env validation may continue.
    """
    if self._validation_mode == ValidationMode.SKIP:
      logging.debug("Skipped Runner/Host environment warning: %s", message)
      return
    elif self._validation_mode == ValidationMode.WARN:
      logging.warn(message)
      return
    elif self._validation_mode == ValidationMode.THROW:
      pass
    elif self._validation_mode == ValidationMode.PROMPT:
      result = input(f"{helper.TTYColor.RED}{message} Continue?"
                     f"{helper.TTYColor.RESET} [Yn]")
      # Accept <enter> as default input to continue.
      if result.lower() != "n":
        return
    else:
      raise ValueError(
          f"Invalid environment validation mode={self._validation_mode}")
    raise ValidationError(
        f"Runner/Host environment requests cannot be fulfilled: {message}")

  def _disable_crowdstrike(self):
    """Crowdstrike security monitoring (for googlers go/crowdstrike-falcon) can
    have quite terrible overhead for each file-access. Disable it to reduce
    flakiness. """
    if not self._platform.is_macos:
      return
    try:
      self._platform.disable_monitoring()
      self._add_min_delay(5)
      return
    except Exception as e:
      logging.exception("Exception: %s", e)
      self.handle_warning(
          "Could not disable go/crowdstrike-falcon monitor which can cause"
          " high background CPU usage.")

  def _check_disk_space(self):
    limit = self._config.disk_min_free_space_gib
    if limit is HostEnvironmentConfig.Ignore:
      return
    # Check the remaining disk space on the FS where we write the results.
    usage = self._platform.disk_usage(self._runner.out_dir)
    free_gib = round(usage.free / 1024 / 1024 / 1024, 2)
    if free_gib < limit:
      self.handle_warning(
          f"Only {free_gib}GiB disk space left, expected at least {limit}GiB.")

  def _check_power(self):
    use_battery = self._config.power_use_battery
    if use_battery is HostEnvironmentConfig.Ignore:
      return
    battery_probes: List[probes.Probe] = []
    # Certain probes may require battery power:
    for probe in self._runner.probes:
      if probe.BATTERY_ONLY:
        battery_probes.append(probe)
    if not use_battery and battery_probes:
      probes_str = ','.join(probe.name for probe in battery_probes)
      self.handle_warning("Requested battery_power=False, "
                          f"but probes={probes_str} require battery power.")
    sys_use_battery = self._platform.is_battery_powered
    if sys_use_battery != use_battery:
      self.handle_warning(
          f"Expected battery_power={use_battery}, "
          f"but the system reported battery_power={sys_use_battery}")

  def _check_cpu_usage(self):
    max_cpu_usage = self._config.cpu_max_usage_percent
    if max_cpu_usage is HostEnvironmentConfig.Ignore:
      return
    cpu_usage_percent = round(100 * self._platform.cpu_usage(), 1)
    if cpu_usage_percent > max_cpu_usage:
      self.handle_warning(f"CPU usage={cpu_usage_percent}% is higher than "
                          f"requested max={max_cpu_usage}%.")

  def _check_cpu_temperature(self):
    min_relative_speed = self._config.cpu_min_relative_speed
    if min_relative_speed is HostEnvironmentConfig.Ignore:
      return
    cpu_speed = self._platform.get_relative_cpu_speed()
    if cpu_speed < min_relative_speed:
      self.handle_warning("CPU thermal throttling is active. "
                          f"Relative speed is {cpu_speed}, "
                          f"but expected at least {min_relative_speed}.")

  def _check_cpu_power_mode(self) -> bool:
    # TODO Implement checks for performance mode
    return True

  def _check_running_binaries(self):
    if self._config.browser_allow_existing_process:
      return
    browser_binaries = helper.group_by(
        self._runner.browsers, key=lambda browser: str(browser.path))
    for proc_info in self._platform.processes(["cmdline", "exe", "pid",
                                               "name"]):
      cmdline = " ".join(proc_info["cmdline"] or "")
      exe = proc_info["exe"]
      for binary, browsers in browser_binaries.items():
        # Add a white-space to get less false-positives
        if f"{binary} " not in cmdline and binary != exe:
          continue
        # Use the first in the group
        browser = browsers[0]
        logging.debug("Binary=%s", binary)
        logging.debug("PS status output:")
        logging.debug("proc(pid=%s, name=%s, cmd=%s)", proc_info["pid"],
                      proc_info["name"], cmdline)
        self.handle_warning(
            f"{browser.app_name} {browser.version} seems to be already running."
        )

  def _check_screen_brightness(self):
    brightness = self._config.screen_brightness_percent
    if brightness is HostEnvironmentConfig.Ignore:
      return
    assert 0 <= brightness <= 100, f"Invalid brightness={brightness}"
    self._platform.set_main_display_brightness(brightness)
    current = self._platform.get_main_display_brightness()
    if current != brightness:
      self.handle_warning(f"Requested main display brightness={brightness}%, "
                          "but got {brightness}%")

  def _check_headless(self):
    requested_headless = self._config.browser_is_headless
    if requested_headless is HostEnvironmentConfig.Ignore:
      return
    if self._platform.is_linux and not requested_headless:
      # Check that the system can run browsers with a UI.
      if not self._platform.has_display:
        self.handle_warning("Requested browser_is_headless=False, "
                            "but no DISPLAY is available to run with a UI.")
    # Check that browsers are running in the requested display mode:
    for browser in self._runner.browsers:
      if browser.is_headless != requested_headless:
        self.handle_warning(
            f"Requested browser_is_headless={requested_headless},"
            f"but browser {browser.short_name} has conflicting "
            f"headless={browser.is_headless}.")

  def _check_probes(self):
    require_probes = self._config.require_probes
    if require_probes is HostEnvironmentConfig.Ignore:
      return
    if self._config.require_probes and not self._runner.probes:
      self.handle_warning("No probes specified.")
    for probe in self._runner.probes:
      probe.pre_check(self)

  def setup(self):
    self.validate()

  def validate(self):
    if self._validation_mode == ValidationMode.SKIP:
      return
    self._disable_crowdstrike()
    self._check_power()
    self._check_disk_space()
    self._check_cpu_usage()
    self._check_cpu_temperature()
    self._check_cpu_power_mode()
    self._check_running_binaries()
    self._check_screen_brightness()
    self._check_headless()
    self._check_probes()
    self._wait_min_time()

  def check_installed(self, binaries, message="Missing binaries: %s"):
    missing = (binary for binary in binaries if not shutil.which(binary))
    if missing:
      self.handle_warning((message % binaries) + " Continue?")
