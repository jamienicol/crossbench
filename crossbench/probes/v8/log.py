# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import multiprocessing
import os
import pathlib
import re
import subprocess
from typing import TYPE_CHECKING, Iterable, List, Optional

import crossbench
import crossbench.config
import crossbench.exception
import crossbench.flags
from crossbench import helper
from crossbench.probes import base

#TODO: fix imports
cb = crossbench

if TYPE_CHECKING:
  import crossbench.env


class V8LogProbe(base.Probe):
  """
  Chromium-only probe that produces a v8.log file with detailed internal V8
  performance and logging information.
  This file can be used by tools hosted on <http://v8.dev/tools>.
  """
  NAME = "v8.log"

  _FLAG_RE = re.compile("^--(prof|log-.*|no-log-.*|)$")

  @classmethod
  def config_parser(cls) -> base.ProbeConfigParser:
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
    parser.add_argument(
        "d8_binary",
        type=parser.existing_file_type,
        help="Path to a D8 binary for extended log processing."
        "If not specified the $D8_PATH env variable is used and/or "
        "default build locations are tried.")
    parser.add_argument(
        "v8_checkout",
        type=parser.existing_file_type,
        help="Path to a V8 checkout for extended log processing."
        "If not specified it is auto inferred from either the provided"
        "d8_binary or standard installation locations.")
    return parser

  def __init__(self,
               log_all: bool = True,
               prof: bool = False,
               js_flags: Optional[Iterable[str]] = None,
               d8_binary: Optional[pathlib.Path] = None,
               v8_checkout: Optional[pathlib.Path] = None):
    super().__init__()
    self._js_flags = cb.flags.JSFlags()
    self._d8_binary = d8_binary
    self._v8_checkout = v8_checkout
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

  @property
  def v8_checkout(self) -> Optional[pathlib.Path]:
    return self._v8_checkout

  @property
  def d8_binary(self) -> Optional[pathlib.Path]:
    return self._d8_binary

  def is_compatible(self, browser) -> bool:
    return isinstance(browser, cb.browsers.Chromium)

  def attach(self, browser):
    super().attach(browser)
    browser.flags.set("--no-sandbox")
    browser.js_flags.update(self._js_flags)

  def pre_check(self, env: cb.env.HostEnvironment):
    super().pre_check(env)
    if env.runner.repetitions != 1:
      env.handle_warning(f"Probe={self.NAME} cannot merge data over multiple "
                         f"repetitions={env.runner.repetitions}.")

  def process_log_files(self,
                        log_files: List[pathlib.Path]) -> List[pathlib.Path]:
    finder = V8ToolsFinder(self)
    if not finder.d8_binary or not finder.tick_processor or not log_files:
      return []
    logging.info(
        "PROBE v8.log: generating profview json data "
        "for %d v8.log files.", len(log_files))
    if self.browser_platform.is_remote:
      # Use loop, as we cannot easily serialize the remote platform.
      return [
          _process_profview_json(finder.d8_binary, finder.tick_processor,
                                 log_file) for log_file in log_files
      ]
    assert self.browser_platform == helper.platform
    with multiprocessing.Pool(processes=4) as pool:
      return list(
          pool.starmap(_process_profview_json,
                       [(finder.d8_binary, finder.tick_processor, log_file)
                        for log_file in log_files]))

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
      # Only convert a v8.log file with profile ticks.
      if "--prof" in self.browser.js_flags:
        log_files.extend(self.probe.process_log_files(log_files))
      return tuple(str(f) for f in log_files)


def _process_profview_json(d8_binary: pathlib.Path,
                           tick_processor: pathlib.Path,
                           log_file: pathlib.Path) -> pathlib.Path:
  env = os.environ.copy()
  # The tick-processor scripts expect D8_PATH to point to the parent dir.
  env["D8_PATH"] = str(d8_binary.parent.resolve())
  result_json = log_file.with_suffix(".profview.json")
  with result_json.open("w", encoding="utf-8") as f:
    helper.platform.sh(
        tick_processor,
        "--preprocess",
        log_file,
        env=env,
        stdout=f,
        stderr=subprocess.DEVNULL)
  return result_json


class V8ToolsFinder:
  """Helper class to find d8 binaries and the tick-processor.
  If no explicit d8 and checkout path are given, $D8_PATH and common v8 and
  chromium installation directories are checked."""

  def __init__(self, log_probe: V8LogProbe):
    self._log_probe = log_probe
    self.d8_binary: Optional[pathlib.Path] = log_probe.d8_binary
    self.v8_checkout: Optional[pathlib.Path] = log_probe.v8_checkout
    self.tick_processor: Optional[pathlib.Path] = None
    self.platform = log_probe.browser_platform
    # A generous list of potential locations of a V8 or chromium checkout
    self._checkout_dirs = [
        # V8 Checkouts
        pathlib.Path.home() / "Documents/v8/v8",
        pathlib.Path.home() / "v8/v8",
        pathlib.Path("C:") / "src/v8/v8",
        # Raw V8 checkouts
        pathlib.Path.home() / "Documents/v8",
        pathlib.Path.home() / "v8",
        pathlib.Path("C:") / "src/v8/",
        # V8 in chromium checkouts
        pathlib.Path.home() / "Documents/chromium/src/v8",
        pathlib.Path.home() / "chromium/src/v8",
        pathlib.Path("C:") / "src/chromium/src/v8",
        # Chromium checkouts
        pathlib.Path.home() / "Documents/chromium/src",
        pathlib.Path.home() / "chromium/src",
        pathlib.Path("C:") / "src/chromium/src",
    ]
    self.d8_binary = self._find_d8()
    if self.d8_binary:
      self.tick_processor = self._find_v8_tick_processor()
    logging.debug("V8ToolsFinder found d8_binary='%s' tick_processor='%s'",
                  self.d8_binary, self.tick_processor)

  def _find_d8(self) -> Optional[pathlib.Path]:
    if self.d8_binary and self.d8_binary.is_file():
      return self.d8_binary
    assert not self.platform.is_remote, (
        "Cannot infer D8 location on remote platform.")
    if "D8_PATH" in os.environ:
      candidate = pathlib.Path(os.environ["D8_PATH"]) / "d8"
      if candidate.is_file():
        return candidate
      candidate = pathlib.Path(os.environ["D8_PATH"])
      if candidate.is_file():
        return candidate
    # Try potential build location
    for candidate_dir in self._checkout_dirs:
      for build_type in ("release", "optdebug", "Default", "Release"):
        candidates = list(candidate_dir.glob(f"out/*{build_type}/d8"))
        if candidates and candidates[0].is_file():
          return candidates[0]
    return None

  def _find_v8_tick_processor(self) -> Optional[pathlib.Path]:
    if self.platform.is_linux:
      tick_processor = "tools/linux-tick-processor"
    elif self.platform.is_macos:
      tick_processor = "tools/mac-tick-processor"
    elif self.platform.is_win:
      tick_processor = "tools/windows-tick-processor.bat"
    else:
      logging.debug(
          "Not looking for the v8 tick-processor on unsupported platform: %s",
          self.platform)
      return None
    if self.v8_checkout and self.v8_checkout.is_dir():
      candidate = self.v8_checkout / tick_processor
      assert candidate.is_file(), (
          f"Provided v8_checkout has no '{tick_processor}' at {candidate}")
    assert self.d8_binary
    # Try inferring the V8 checkout from a built d8:
    # .../foo/v8/v8/out/x64.release/d8
    candidate = self.d8_binary.parents[2] / tick_processor
    if candidate.is_file():
      return candidate
    for candidate_dir in self._checkout_dirs:
      candidate = candidate_dir / tick_processor
      if candidate.is_file():
        return candidate
    return None
