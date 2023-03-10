# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import pathlib
import re
import tempfile
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from crossbench import helper
from crossbench.browsers.base import (Browser, Viewport, convert_flags_to_label)
from crossbench.flags import ChromeFeatures, ChromeFlags, Flags, JSFlags

if TYPE_CHECKING:
  from crossbench.runner import Run, Runner


class Chromium(Browser):
  MIN_HEADLESS_NEW_VERSION = 112
  DEFAULT_FLAGS = [
      "--no-default-browser-check",
      "--disable-component-update",
      "--disable-sync",
      "--no-experiments",
      "--enable-benchmarking",
      "--disable-extensions",
      "--no-first-run",
      # limit the effects of putting the browser in the background:
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
  ]

  @classmethod
  def default_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chromium",
        macos=["Chromium.app"],
        linux=["google-chromium", "chromium"],
        win=["Google/Chromium/Application/chromium.exe"])

  @classmethod
  def default_flags(cls,
                    initial_data: Flags.InitialDataType = None) -> ChromeFlags:
    return ChromeFlags(initial_data)

  def __init__(
      self,
      label: str,
      path: pathlib.Path,
      js_flags: Flags.InitialDataType = None,
      flags: Flags.InitialDataType = None,
      cache_dir: Optional[pathlib.Path] = None,
      type: str = "chromium",  # pylint: disable=redefined-builtin
      viewport: Viewport = Viewport.DEFAULT,
      platform: Optional[helper.Platform] = None):
    super().__init__(
        label, path, type=type, viewport=viewport, platform=platform)
    assert not isinstance(js_flags, str), (
        f"js_flags should be a list, but got: {repr(js_flags)}")
    assert not isinstance(
        flags, str), (f"flags should be a list, but got: {repr(flags)}")
    self._flags: ChromeFlags = self.default_flags(self.DEFAULT_FLAGS)
    self._flags.update(flags)
    self.js_flags.update(js_flags)
    if cache_dir is None:
      cache_dir = self._flags.get("--user-data-dir")
    if cache_dir is None:
      # pylint: disable=bad-option-value, consider-using-with
      self.cache_dir = pathlib.Path(
          tempfile.TemporaryDirectory(prefix=type).name)
      self.clear_cache_dir = True
    else:
      self.cache_dir = cache_dir
      self.clear_cache_dir = False
    self._stdout_log_file = None

  def _extract_version(self) -> str:
    assert self.path
    version_string = self.platform.app_version(self.path)
    # Sample output: "Chromium 90.0.4430.212 dev" => "90.0.4430.212"
    return re.findall(r"[\d\.]+", version_string)[0]

  @property
  def is_headless(self) -> bool:
    return "--headless" in self._flags

  @property
  def chrome_log_file(self) -> pathlib.Path:
    assert self.log_file
    return self.log_file.with_suffix(f".{self.type}.log")

  @property
  def js_flags(self) -> JSFlags:
    return self._flags.js_flags

  @property
  def features(self) -> ChromeFeatures:
    return self._flags.features

  def exec_apple_script(self, script: str):
    assert self.platform.is_macos
    return self.platform.exec_apple_script(script)

  def details_json(self) -> Dict[str, Any]:
    details = super().details_json()
    if self.log_file:
      details["log"][self.type] = str(self.chrome_log_file)
      details["log"]["stdout"] = str(self.stdout_log_file)
    details["js_flags"] = tuple(self.js_flags.get_list())
    return details

  def _get_browser_flags(self, run: Run) -> Tuple[str, ...]:
    js_flags_copy = self.js_flags.copy()
    js_flags_copy.update(run.extra_js_flags)

    flags_copy = self.flags.copy()
    flags_copy.update(run.extra_flags)
    self._handle_viewport_flags(flags_copy)

    if len(js_flags_copy):
      flags_copy["--js-flags"] = str(js_flags_copy)
    if user_data_dir := self.flags.get("--user-data-dir"):
      assert user_data_dir == self.cache_dir, (
          f"--user-data-dir path: {user_data_dir} was passed"
          f"but does not match cache-dir: {self.cache_dir}")
    if self.cache_dir:
      flags_copy["--user-data-dir"] = str(self.cache_dir)
    if self.log_file:
      flags_copy.set("--enable-logging")
      flags_copy["--log-file"] = str(self.chrome_log_file)

    return tuple(flags_copy.get_list())

  def _handle_viewport_flags(self, flags: Flags):
    self._sync_viewport_flag(flags, "--start-fullscreen",
                             self.viewport.is_fullscreen, Viewport.FULLSCREEN)
    self._sync_viewport_flag(flags, "--start-maximized",
                             self.viewport.is_maximized, Viewport.MAXIMIZED)
    self._sync_viewport_flag(flags, "--headless", self.viewport.is_headless,
                             Viewport.HEADLESS)
    # M112 added --headless=new as replacement for --headless
    if "--headless" in flags and (self.major_version >=
                                  self.MIN_HEADLESS_NEW_VERSION):
      if flags["--headless"] is None:
        logging.info("Replacing --headless with --headless=new")
        flags.set("--headless", "new", override=True)

    if self.viewport.is_default:
      update_viewport = False
      width, height = self.viewport.size
      x, y = self.viewport.position
      if "--window-size" in flags:
        update_viewport = True
        width, height = map(int, flags["--window-size"].split(","))
      if "--window-position" in flags:
        update_viewport = True
        x, y = map(int, flags["--window-position"].split(","))
      if update_viewport:
        self.viewport = Viewport(width, height, x, y)
    if self.viewport.has_size:
      flags["--window-size"] = f"{self.viewport.width},{self.viewport.height}"
      flags["--window-position"] = f"{self.viewport.x},{self.viewport.y}"
    else:
      for flag in ("--window-position", "--window-size"):
        if flag in flags:
          flag_value = flags[flag]
          raise ValueError(f"Viewport {self.viewport} conflicts with flag "
                           f"{flag}={flag_value}")

  def get_label_from_flags(self) -> str:
    return convert_flags_to_label(*self.flags, *self.js_flags)

  def start(self, run: Run) -> None:
    # TODO: fix applescript version
    raise NotImplementedError(
        "Running the browser with AppleScript is currently broken.")

  def _start_broken(self, run: Run) -> None:
    runner = run.runner
    assert self.platform.is_macos, (
        f"Sorry, f{self.__class__} is only supported on MacOS for now")
    assert not self._is_running
    assert self._stdout_log_file is None
    if self.log_file:
      self._stdout_log_file = self.stdout_log_file.open("w", encoding="utf-8")
    # self._pid = runner.popen(
    #     self.path, *self._get_browser_flags(run), stdout=self._stdout_log_file)
    runner.wait(0.5)
    self.exec_apple_script(f"""
tell application "{self.app_name}"
    activate
    set the bounds of the first window to {{50,50,1050,1050}}
end tell
    """)
    self._is_running = True

  def quit(self, runner: Runner) -> None:
    super().quit(runner)
    if self._stdout_log_file:
      self._stdout_log_file.close()
      self._stdout_log_file = None

  def show_url(self, runner: Runner, url: str) -> None:
    self.exec_apple_script(f"""
tell application "{self.app_name}"
    activate
    set URL of active tab of front window to '{url}'
end tell
    """)