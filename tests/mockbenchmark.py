# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
import psutil
from typing import Optional

import crossbench as cb

FlagsInitialDataType = cb.flags.Flags.InitialDataType

GiB = 1014**3

ActivePlatformClass = type(cb.helper.platform)


class MockPlatform(ActivePlatformClass):

  def __init__(self, is_battery_powered=False):
    self._is_battery_powered = is_battery_powered

  @property
  def is_battery_powered(self):
    return self._is_battery_powered

  def disk_usage(self, path):
    return psutil._common.sdiskusage(
        total=GiB * 100, used=20 * GiB, free=80 * GiB, percent=20)

  def cpu_usage(self):
    return 0.1

  def get_hardware_details(self):
    return "CPU: 20-core 3.1 GHz"

  def sleep(self, duration):
    pass


mock_platform = MockPlatform()


class MockBrowser(cb.browsers.Browser):
  BIN_PATH = None
  VERSION = "100.22.33.44"

  @classmethod
  def setup_fs(cls, fs):
    if cb.helper.platform.is_macos:
      fs.create_file(cls.BIN_PATH / "Contents" / "MacOS" / "Chrome")
    else:
      fs.create_file(cls.BIN_PATH)

  def __init__(self,
               label: str,
               path: Optional[pathlib.Path] = None,
               browser_name:str = "chrome",
               *args,
               **kwargs):
    path = path or pathlib.Path(self.BIN_PATH)
    kwargs["type"] = browser_name
    super().__init__(label, path, *args, **kwargs)
    self.url_list = []
    self.js_list = []
    self.js_side_effect = []
    self.run_js_side_effect = []
    self.did_run = False
    self.clear_cache_dir = False

  def clear_cache(self, runner: cb.runner.Runner):
    pass

  def start(self, run: cb.runner.Run):
    assert not self._is_running
    self._is_running = True
    self.did_run = True
    self.run_js_side_effect = list(self.js_side_effect)

  def force_quit(self):
    # Assert that start() was called before force_quit()
    assert self._is_running
    self._is_running = False

  def _extract_version(self):
    return self.VERSION

  def show_url(self, runner, url):
    self.url_list.append(url)

  def js(self, runner, script, timeout=None, arguments=()):
    self.js_list.append(script)
    if self.js_side_effect is None:
      return None
    assert self.run_js_side_effect, (
        "Not enough mock js_side_effect available. "
        "Please add another js_side_effect entry for "
        f"arguments={arguments} \n"
        f"Script: {script}")
    return self.run_js_side_effect.pop(0)


class MockBrowserStable(MockBrowser):
  if cb.helper.platform.is_macos:
    BIN_PATH = pathlib.Path("/Applications/Chrome.app")
  else:
    BIN_PATH = pathlib.Path("/usr/bin/chrome")


class MockBrowserDev(MockBrowser):
  if cb.helper.platform.is_macos:
    BIN_PATH = pathlib.Path("/Applications/ChromeDev.app")
  else:
    BIN_PATH = pathlib.Path("/usr/bin/chrome-dev")
