# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

from crossbench.browsers.chromium import (ChromiumWebDriver,
                                          ChromiumWebDriverAndroid)
from crossbench.browsers.splash_screen import SplashScreen
from crossbench.browsers.viewport import Viewport

if TYPE_CHECKING:
  from selenium.webdriver.chromium.webdriver import ChromiumDriver

  from crossbench.flags import Flags
  from crossbench.platform import Platform


class ChromeWebDriver(ChromiumWebDriver):

  WEB_DRIVER_OPTIONS = ChromeOptions
  WEB_DRIVER_SERVICE = ChromeService

  def __init__(self,
               label: str,
               path: pathlib.Path,
               js_flags: Flags.InitialDataType = None,
               flags: Flags.InitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               driver_path: Optional[pathlib.Path] = None,
               viewport: Viewport = Viewport.DEFAULT,
               splash_screen: SplashScreen = SplashScreen.DEFAULT,
               platform: Optional[Platform] = None):
    super().__init__(
        label,
        path,
        js_flags,
        flags,
        cache_dir,
        type="chrome",
        driver_path=driver_path,
        viewport=viewport,
        splash_screen=splash_screen,
        platform=platform)

  def _create_driver(self, options, service: ChromeService) -> ChromiumDriver:
    return webdriver.Chrome(  # pytype: disable=wrong-keyword-args
        options=options, service=service)


class ChromeWebDriverAndroid(ChromiumWebDriverAndroid, ChromeWebDriver):
  pass
