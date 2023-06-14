# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

from crossbench.browsers.chromium import ChromiumAppleScript

from .chrome import ChromePathMixin

if TYPE_CHECKING:
  from typing import Optional

  from selenium.webdriver.chromium.webdriver import ChromiumDriver

  from crossbench.browsers.splash_screen import SplashScreen
  from crossbench.browsers.viewport import Viewport
  from crossbench.flags import Flags
  from crossbench.platform import Platform


class ChromeAppleScript(ChromePathMixin, ChromiumAppleScript):

  WEB_DRIVER_OPTIONS = ChromeOptions
  WEB_DRIVER_SERVICE = ChromeService

  def __init__(
      self,
      label: str,
      path: pathlib.Path,
      flags: Flags.InitialDataType = None,
      js_flags: Flags.InitialDataType = None,
      cache_dir: Optional[pathlib.Path] = None,
      type: str = "chrome",  # pylint: disable=redefined-builtin
      viewport: Optional[Viewport] = None,
      splash_screen: Optional[SplashScreen] = None,
      platform: Optional[Platform] = None):
    super().__init__(
        label,
        path,
        flags,
        js_flags,
        cache_dir,
        type=type,
        viewport=viewport,
        splash_screen=splash_screen,
        platform=platform)

  def _create_driver(self, options, service) -> ChromiumDriver:
    return webdriver.Chrome(  # pytype: disable=wrong-keyword-args
        options=options, service=service)
