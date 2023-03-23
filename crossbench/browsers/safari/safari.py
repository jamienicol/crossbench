# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Optional, Tuple

from crossbench import helper
from crossbench.browsers.browser import Browser
from crossbench.browsers.viewport import Viewport

if TYPE_CHECKING:
  from crossbench.flags import Flags
  from crossbench.runner import Run, Runner


class Safari(Browser):

  @classmethod
  def default_path(cls) -> pathlib.Path:
    return pathlib.Path("/Applications/Safari.app")

  @classmethod
  def technology_preview_path(cls) -> pathlib.Path:
    return pathlib.Path("/Applications/Safari Technology Preview.app")

  def __init__(self,
               label: str,
               path: pathlib.Path,
               flags: Flags.InitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               viewport: Viewport = Viewport.DEFAULT,
               platform: Optional[helper.MacOSPlatform] = None):
    super().__init__(
        label, path, flags, type="safari", viewport=viewport, platform=platform)
    assert self.platform.is_macos, "Safari only works on MacOS"
    assert self.path
    self.bundle_name = self.path.stem.replace(" ", "")
    assert cache_dir is None, "Cannot set custom cache dir for Safari"
    self.cache_dir = pathlib.Path(
        f"~/Library/Containers/com.apple.{self.bundle_name}/Data/Library/Caches"
    ).expanduser()

  def _get_browser_flags(self, run: Run) -> Tuple[str, ...]:
    flags_copy = self.flags.copy()
    flags_copy.update(run.extra_flags)
    return tuple(flags_copy.get_list())

  def _extract_version(self) -> str:
    assert self.path
    app_path = self.path.parents[2]
    return self.platform.app_version(app_path)

  def start(self, run: Run) -> None:
    assert self.platform.is_macos
    assert not self._is_running
    self.platform.exec_apple_script(f"""
tell application "{self.app_name}"
  activate
end tell
    """)
    self.platform.sleep(1)
    self.platform.exec_apple_script(f"""
tell application "{self.app_name}"
  tell application "System Events"
      to click menu item "New Private Window"
      of menu "File" of menu bar 1
      of process '{self.bundle_name}'
      if {self.viewport.is_fullscreen} then
        keystroke "f" using {{command down, control down}}
      end if
  set URL of current tab of front window to ''
  if {not self.viewport.is_fullscreen} then
    set the bounds of the first window
        to {{{self.viewport.x},{self.viewport.y},{self.viewport.width},{self.viewport.height}}}
  end if
  tell application "System Events"
      to keystroke "e" using {{command down, option down}}
  tell application "System Events"
      to click menu item 1 of menu 2 of menu bar 1
      of process '{self.bundle_name}'
  tell application "System Events"
      to set position of window 1
      of process '{self.bundle_name}' to {400, 400}
end tell
    """)
    self.platform.sleep(2)
    self._is_running = True

  def show_url(self, runner: Runner, url: str) -> None:
    self.platform.exec_apple_script(f"""
tell application "{self.app_name}"
    activate
    set URL of current tab of front window to '{url}'
end tell
    """)
