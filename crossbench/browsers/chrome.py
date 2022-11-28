# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Optional, Type

import crossbench as cb
import crossbench.flags
from crossbench import helper
from crossbench.browsers.chromium import Chromium, ChromiumWebDriver

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

if TYPE_CHECKING:
  from selenium.webdriver.chromium.webdriver import ChromiumDriver

FlagsInitialDataType = cb.flags.Flags.InitialDataType


class Chrome(Chromium):


  @classmethod
  def default_path(cls) -> pathlib.Path:
    return cls.stable_path()

  @classmethod
  def stable_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Stable",
        macos=["Google Chrome.app"],
        linux=["google-chrome", "chrome"],
        win=["Google/Chrome/Application/chrome.exe"])

  @classmethod
  def beta_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Beta",
        macos=["Google Chrome Beta.app"],
        linux=["google-chrome-beta"],
        win=["Google/Chrome Beta/Application/chrome.exe"])

  @classmethod
  def dev_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Dev",
        macos=["Google Chrome Dev.app"],
        linux=["google-chrome-unstable"],
        win=["Google/Chrome Dev/Application/chrome.exe"])

  @classmethod
  def canary_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Canary",
        macos=["Google Chrome Canary.app"],
        win=["Google/Chrome SxS/Application/chrome.exe"])

  def __init__(self,
               label: str,
               path: pathlib.Path,
               js_flags: FlagsInitialDataType = None,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               platform: Optional[helper.Platform] = None):
    super().__init__(
        label, path, js_flags, flags, cache_dir, type="chrome", platform=platform)


class ChromeWebDriver(ChromiumWebDriver):

  WebDriverOptions = ChromeOptions
  WebDriverService = ChromeService

  def __init__(self,
               label: str,
               path: pathlib.Path,
               js_flags: FlagsInitialDataType = None,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               driver_path: Optional[pathlib.Path] = None,
               platform: Optional[helper.Platform] = None):
    super().__init__(
        label,
        path,
        js_flags,
        flags,
        cache_dir,
        type="chrome",
        driver_path=driver_path,
        platform=platform)

  def _create_driver(self, options, service) -> ChromiumDriver:
    return webdriver.Chrome(options=options, service=service)
