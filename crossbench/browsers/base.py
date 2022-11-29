# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import html
import logging
import pathlib
import re
import shutil
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Sequence, Set

import crossbench as cb
import crossbench.flags
import crossbench.probes.base
import crossbench.runner
from crossbench import helper

# =============================================================================

FlagsInitialDataType = cb.flags.Flags.InitialDataType

BROWSERS_CACHE = pathlib.Path(__file__).parent.parent / ".browsers-cache"

# =============================================================================


class Browser(abc.ABC):

  @classmethod
  def default_flags(cls, initial_data: FlagsInitialDataType = None
                   ) -> cb.flags.Flags:
    return cb.flags.Flags(initial_data)

  def __init__(self,
               label: str,
               path: Optional[pathlib.Path],
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               type: Optional[str] = None,
               platform: Optional[helper.Platform] = None):
    self.platform = platform or helper.platform
    # Marked optional to make subclass constructor calls easier with pytype.
    assert type
    self.type: str = type
    self.label: str = label
    self.path: Optional[pathlib.Path] = path
    if path:
      self.path = self._resolve_binary(path)
      self.version: str = self._extract_version()
      self.major_version: int = int(self.version.split(".")[0])
      short_name = f"{self.type}_v{self.major_version}_{self.label}".lower()
    else:
      short_name = f"{self.type}_{self.label}".lower()
    self.short_name: str = short_name.replace(" ", "_")
    self.width: int = 1500
    self.height: int = 1000
    self.x: int = 10
    # Move down to avoid menu bars
    self.y: int = 50
    self._is_running: bool = False
    self.cache_dir: Optional[pathlib.Path] = cache_dir
    self.clear_cache_dir: bool = True
    self._pid: Optional[int] = None
    self._probes: Set[cb.probes.Probe] = set()
    self._flags: cb.flags.Flags = self.default_flags(flags)
    self.log_file: Optional[pathlib.Path] = None

  @property
  def is_headless(self) -> bool:
    return False

  @property
  def flags(self) -> cb.flags.Flags:
    return self._flags

  @property
  def pid(self):
    return self._pid

  @property
  def is_local(self) -> bool:
    return True

  def set_log_file(self, path):
    self.log_file = path

  @property
  def stdout_log_file(self) -> pathlib.Path:
    assert self.log_file
    return self.log_file.with_suffix(".stdout.log")

  def _resolve_binary(self, path: pathlib.Path) -> pathlib.Path:
    assert path.exists(), f"Binary at path={path} does not exist."
    self.app_path = path
    self.app_name: str = self.app_path.stem
    if self.platform.is_macos:
      path = self._resolve_macos_binary(path)
    assert path.is_file(), (f"Binary at path={path} is not a file.")
    return path

  def _resolve_macos_binary(self, path: pathlib.Path) -> pathlib.Path:
    assert self.platform.is_macos
    candidate = self.platform.search_binary(path)
    if not candidate or not candidate.is_file():
      raise ValueError(f"Could not find browser executable in {path}")
    return candidate

  def attach_probe(self, probe: cb.probes.Probe):
    self._probes.add(probe)
    probe.attach(self)

  def details_json(self) -> Dict[str, Any]:
    return {
        "label": self.label,
        "browser": self.type,
        "short_name": self.short_name,
        "app_name": self.app_name,
        "version": self.version,
        "flags": tuple(self.flags.get_list()),
        "js_flags": tuple(),
        "path": str(self.path),
        "clear_cache_dir": self.clear_cache_dir,
        "major_version": self.major_version,
        "log": {}
    }

  def setup_binary(self, runner: cb.runner.Runner):
    pass

  def setup(self, run: cb.runner.Run):
    assert not self._is_running
    runner = run.runner
    self.clear_cache(runner)
    self.start(run)
    assert self._is_running
    self._prepare_temperature(run)
    self.show_url(runner, self.info_data_url(run))
    runner.wait(runner.default_wait)

  @abc.abstractmethod
  def _extract_version(self) -> str:
    pass

  def clear_cache(self, runner: cb.runner.Runner):
    if self.clear_cache_dir and self.cache_dir and self.cache_dir.exists():
      shutil.rmtree(self.cache_dir)

  @abc.abstractmethod
  def start(self, run: cb.runner.Run):
    pass

  def _prepare_temperature(self, run: cb.runner.Run):
    """Warms up the browser by loading the page 3 times."""
    runner = run.runner
    if run.temperature != "cold" and run.temperature:
      for _ in range(3):
        # TODO(cbruni): add no_collect argument
        run.story.run(run)
        runner.wait(run.story.duration / 2)
        self.show_url(runner, "about:blank")
        runner.wait(runner.default_wait)

  def info_data_url(self, run):
    page = ("<html><head>"
            "<title>Browser Details</title>"
            "<style>"
            """
            html { font-family: sans-serif; }
            dl {
              display: grid;
              grid-template-columns: max-content auto;
            }
            dt { grid-column-start: 1; }
            dd { grid-column-start: 2;  font-family: monospace; }
            """
            "</style>"
            "<head><body>"
            f"<h1>{html.escape(self.type)} {html.escape(self.version)}</h2>"
            "<dl>")
    for property_name, value in self.details_json().items():
      page += f"<dt>{html.escape(property_name)}</dt>"
      page += f"<dd>{html.escape(str(value))}</dd>"
    page += "</dl></body></html>"
    data_url = f"data:text/html;charset=utf-8,{urllib.parse.quote(page)}"
    return data_url

  def quit(self, runner: cb.runner.Runner):
    assert self._is_running
    try:
      self.force_quit()
    finally:
      self._pid = None

  def force_quit(self):
    logging.info("QUIT")
    if self.platform.is_macos:
      self.platform.exec_apple_script(f"""
  tell application "{self.app_name}"
    quit
  end tell
      """)
    elif self._pid:
      self.platform.terminate(self._pid)
    self._is_running = False

  @abc.abstractmethod
  def js(self,
         runner: cb.runner.Runner,
         script: str,
         timeout: Optional[float] = None,
         arguments: Sequence[object] = ()):
    pass

  @abc.abstractmethod
  def show_url(self, runner: cb.runner.Runner, url):
    pass


_FLAG_TO_PATH_RE = re.compile(r"[-/\\:\.]")


def convert_flags_to_label(*flags, index: Optional[int] = None) -> str:
  label = "default"
  if flags:
    label = _FLAG_TO_PATH_RE.sub("_", "_".join(flags).replace("--", ""))
  if index is None:
    return label
  return f"{str(index).rjust(2,'0')}_{label}"