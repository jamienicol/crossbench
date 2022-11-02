# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable, Optional

import crossbench as cb
if TYPE_CHECKING:
  import crossbench.env

import crossbench.flags
from crossbench import helper
from crossbench.probes import base


class V8LogProbe(base.Probe):
  """
  Chromium-only probe that produces a v8.log file with detailed internal V8
  performance and logging information.
  This file can be used by tools hosted on <http://v8.dev/tools>.
  """
  NAME = "v8.log"

  _FLAG_RE = re.compile("^--(prof|log-.*|no-log-.*|)$")

  @classmethod
  def config_parser(cls):
    parser = super().config_parser()
    parser.add_argument(
        "log_all",
        type=bool,
        default=True,
        help="Enable all v8 logging (equivalent to --log-all)")
    parser.add_argument(
        "prof",
        type=bool,
        default=False,
        help="Enable v8-profiling (equivalent to --prof)")
    parser.add_argument(
        "js_flags",
        type=str,
        default=[],
        is_list=True,
        help="Manually pass --log-.* flags to V8")
    return parser

  def __init__(self,
               log_all: bool = True,
               prof: bool = False,
               js_flags: Optional[Iterable[str]] = None):
    super().__init__()
    self._js_flags = cb.flags.JSFlags()
    assert isinstance(log_all,
                      bool), (f"Expected bool value, got log_all={log_all}")
    assert isinstance(prof, bool), f"Expected bool value, got log_all={prof}"
    if log_all:
      self._js_flags.set("--log-all")
    if prof:
      self._js_flags.set("--prof")
    js_flags = js_flags or []
    for flag in js_flags:
      if self._FLAG_RE.match(flag):
        self._js_flags.set(flag)
      else:
        raise ValueError(f"Non-v8.log-related flag detected: {flag}")
    assert len(self._js_flags) > 0, "V8LogProbe has no effect"

  @property
  def js_flags(self) -> cb.flags.JSFlags:
    return self._js_flags.copy()

  def is_compatible(self, browser) -> bool:
    return browser.type == "chrome"

  def attach(self, browser):
    super().attach(browser)
    browser.flags.set("--no-sandbox")
    browser.js_flags.update(self._js_flags)

  def pre_check(self, env: cb.env.HostEnvironment):
    super().pre_check(env)
    if env.runner.repetitions != 1:
      env.handle_warning(f"Probe={self.NAME} cannot merge data over multiple "
                         f"repetitions={env.runner.repetitions}.")

  class Scope(base.Probe.Scope):

    @property
    def results_file(self):
      # Put v8.log files into separate dirs in case we have multiple isolates
      log_dir = super().results_file
      log_dir.mkdir(exist_ok=True)
      return log_dir / self.probe.results_file_name

    def setup(self, run):
      run.extra_js_flags["--logfile"] = str(self.results_file)

    def start(self, run):
      pass

    def stop(self, run):
      pass

    def tear_down(self, run):
      log_dir = self.results_file.parent
      log_files = helper.sort_by_file_size(log_dir.glob("*-v8.log"))
      # Sort by file size, biggest first
      return tuple(str(f) for f in log_files)
