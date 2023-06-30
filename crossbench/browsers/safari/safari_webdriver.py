# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Optional

from selenium import webdriver
from selenium.webdriver.safari.options import Options as SafariOptions
from selenium.webdriver.safari.service import Service as SafariService

from crossbench.browsers.splash_screen import SplashScreen
from crossbench.browsers.webdriver import WebDriverBrowser
from crossbench.browsers.viewport import Viewport

from .safari import Safari

if TYPE_CHECKING:
  from crossbench.flags import Flags
  from crossbench.platform.macos import MacOSPlatform
  from crossbench.runner import Run, Runner


class SafariWebDriver(WebDriverBrowser, Safari):

  def __init__(
      self,
      label: str,
      path: pathlib.Path,
      flags: Optional[Flags.InitialDataType] = None,
      js_flags: Optional[Flags.InitialDataType] = None,
      cache_dir: Optional[pathlib.Path] = None,
      type: str = "safari",  # pylint: disable=redefined-builtin
      driver_path: Optional[pathlib.Path] = None,
      viewport: Optional[Viewport] = None,
      splash_screen: Optional[SplashScreen] = None,
      platform: Optional[MacOSPlatform] = None):
    super().__init__(label, path, flags, js_flags, cache_dir, type, driver_path,
                     viewport, splash_screen, platform)
    assert self.platform.is_macos

  def clear_cache(self, runner: Runner) -> None:
    # skip the default caching, and only do it after launching the browser
    # via selenium.
    pass

  def _find_driver(self) -> pathlib.Path:
    assert self.path
    driver_path = self.path.parent / "safaridriver"
    if not driver_path.exists():
      # The system-default Safari version doesn't come with the driver
      driver_path = pathlib.Path("/usr/bin/safaridriver")
    return driver_path

  def _start_driver(self, run: Run,
                    driver_path: pathlib.Path) -> webdriver.Safari:
    assert not self._is_running
    logging.info("STARTING BROWSER: browser: %s driver: %s", self.path,
                 driver_path)

    options = SafariOptions()
    args = self._get_browser_flags_for_run(run)
    for arg in args:
      options.add_argument(arg)
    options.binary_location = str(self.path)

    options.set_capability("safari.cleanSession", "true")
    # Don't wait for document-ready.
    options.set_capability("pageLoadStrategy", "eager")
    # Enable browser logging
    options.set_capability("safari:diagnose", "true")
    if "Technology Preview" in self.app_name:
      options.set_capability("browserName", "Safari Technology Preview")
      options.use_technology_preview = True

    service = SafariService(executable_path=str(driver_path),)
    driver = webdriver.Safari(
        service=service,
        options=options,
        desired_capabilities=options.to_capabilities())
    assert driver.session_id, "Could not start webdriver"
    self._clear_cache()
    logs = (
        pathlib.Path("~/Library/Logs/com.apple.WebDriver/").expanduser() /
        driver.session_id)
    all_logs = list(logs.glob("safaridriver*"))
    if all_logs:
      self.log_file = all_logs[0]
      assert self.log_file.is_file()
    return driver

  def _check_driver_version(self) -> None:
    # The bundled driver is always ok
    assert self._driver_path
    for parent in self._driver_path.parents:
      if parent == self.path.parent:
        return
    version = self.platform.sh_stdout(self._driver_path, "--version")
    assert str(self.major_version) in version, (
        f"safaridriver={self._driver_path} version='{version}' "
        f" doesn't match safari version={self.major_version}")

  def quit(self, runner: Runner) -> None:
    super().quit(runner)
    # Safari needs some additional push to quit properly
    self.platform.exec_apple_script(f"""
        tell application "{self.app_name}"
          quit
        end tell""")
