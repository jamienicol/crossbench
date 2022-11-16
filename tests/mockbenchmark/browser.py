# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
from typing import List, Optional, Tuple, Type

import crossbench as cb
from crossbench import cli
from crossbench import flags
from crossbench import helper


class MockBrowser(cb.browsers.Browser):
  APP_PATH: pathlib.Path = pathlib.Path("/")
  VERSION = "100.22.33.44"

  @classmethod
  def setup_fs(cls, fs, bin_name: str = "Chrome"):
    cls.setup_bin(fs, cls.APP_PATH, bin_name)

  @classmethod
  def setup_bin(cls, fs, bin_path: pathlib.Path, bin_name: str):
    if cb.helper.platform.is_macos:
      assert bin_path.suffix == ".app"
      bin_path = bin_path / "Contents" / "MacOS" / bin_name
    elif cb.helper.platform.is_win:
      assert bin_path.suffix == ".exe"
    fs.create_file(bin_path)

  @classmethod
  def default_flags(cls, initial_data: cb.flags.Flags.InitialDataType = None):
    return cb.flags.ChromeFlags(initial_data)

  def __init__(self,
               label: str,
               path: Optional[pathlib.Path] = None,
               browser_name: str = "chrome",
               *args,
               **kwargs):
    assert self.APP_PATH
    path = path or pathlib.Path(self.APP_PATH)
    self.app_path = path
    kwargs["type"] = browser_name
    super().__init__(label, path, *args, **kwargs)
    self.url_list: List[str] = []
    self.js_list: List[str] = []
    self.js_side_effect: List[str] = []
    self.run_js_side_effect: List[str] = []
    self.did_run: bool = False
    self.clear_cache_dir: bool = False
    self.js_flags = self.flags.js_flags

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


if helper.platform.is_macos:
  APP_ROOT = pathlib.Path("/Applications")
elif helper.platform.is_win:
  APP_ROOT = pathlib.Path("C:/Program Files/Google")
else:
  APP_ROOT = pathlib.Path("/usr/bin")


class MockChromeStable(MockBrowser):
  if helper.platform.is_macos:
    APP_PATH = APP_ROOT / "Google Chrome.app"
  elif helper.platform.is_win:
    APP_PATH = APP_ROOT / "Chrome/Application/chrome.exe"
  else:
    APP_PATH = APP_ROOT / "google-chrome"


class MockChromeBeta(MockBrowser):
  if cb.helper.platform.is_macos:
    APP_PATH = APP_ROOT / "Google Chrome Beta.app"
  elif helper.platform.is_win:
    APP_PATH = APP_ROOT / "Chrome Beta/Application/chrome.exe"
  else:
    APP_PATH = APP_ROOT / "google-chrome-beta"


class MockChromeDev(MockBrowser):
  if helper.platform.is_macos:
    APP_PATH = APP_ROOT / "Google Chrome Dev.app"
  elif helper.platform.is_win:
    APP_PATH = APP_ROOT / "Chrome Dev/Application/chrome.exe"
  else:
    APP_PATH = APP_ROOT / "google-chrome-unstable"


class MockChromeCanary(MockBrowser):
  if helper.platform.is_macos:
    APP_PATH = APP_ROOT / "Google Chrome Canary.app"
  elif helper.platform.is_win:
    APP_PATH = APP_ROOT / "Chrome SxS/Application/chrome.exe"
  else:
    APP_PATH = APP_ROOT / "google-chrome-canary"


class MockSafari(MockBrowser):
  if helper.platform.is_macos:
    APP_PATH = APP_ROOT / "Safari.app"
  elif helper.platform.is_win:
    APP_PATH = APP_ROOT / "Unsupported/Safari.exe"
  else:
    APP_PATH = pathlib.Path('/unsupported-platform/Safari')

  @classmethod
  def setup_fs(cls, fs):
    return super().setup_fs(fs, bin_name="Safari")


class MockSafariTechnologyPreview(MockBrowser):
  if cb.helper.platform.is_macos:
    APP_PATH = APP_ROOT / "Safari Technology Preview.app"
  elif helper.platform.is_win:
    APP_PATH = APP_ROOT / "Unsupported/Safari Technology Preview.exe"
  else:
    APP_PATH = pathlib.Path('/unsupported-platform/Safari Technology Preview')

  @classmethod
  def setup_fs(cls, fs):
    return super().setup_fs(fs, bin_name="Safari Technology Preview")


ALL: Tuple[Type[MockBrowser], ...] = (
    MockChromeCanary,
    MockChromeDev,
    MockChromeBeta,
    MockChromeStable,
    MockSafari,
    MockSafariTechnologyPreview,
)
