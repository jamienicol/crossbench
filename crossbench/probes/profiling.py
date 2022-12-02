# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import json
import logging
import multiprocessing
import pathlib
import signal
import subprocess
import time
from typing import TYPE_CHECKING, List, Optional

import crossbench
import crossbench.probes.v8
from crossbench import helper
from crossbench.probes import base

#TODO: fix imports
cb = crossbench

if TYPE_CHECKING:
  import crossbench.browsers
  import crossbench.env
  import crossbench.runner


class ProfilingProbe(base.Probe):
  """
  General-purpose sampling profiling probe.

  Implementation:
  - Uses linux-perf on linux platforms (per browser/renderer process)
  - Uses xctrace on MacOS (currently only system-wide)

  For linux-based Chromium browsers it also injects JS stack samples with names
  from V8. For Googlers it additionally can auto-upload symbolized profiles to
  pprof.
  """
  NAME = "profiling"

  JS_FLAGS_PERF = (
      "--perf-prof",
      "--no-write-protect-code-memory",
  )
  _INTERPRETED_FRAMES_FLAG = "--interpreted-frames-native-stack"
  IS_GENERAL_PURPOSE = True

  @classmethod
  def config_parser(cls):
    parser = super().config_parser()
    parser.add_argument(
        "js",
        type=bool,
        default=True,
        help="Chrome-only: expose JS function names to the native profiler")
    parser.add_argument(
        "browser_process",
        type=bool,
        default=False,
        help=("Chrome-only: also profile the browser process, "
              "(as opposed to only renderer processes)"))
    parser.add_argument(
        "v8_interpreted_frames",
        type=bool,
        default=True,
        help=(
            f"Chrome-only: Sets the {cls._INTERPRETED_FRAMES_FLAG} flag for "
            "V8, which exposes interpreted frames as native frames. "
            "Note that this comes at an additional performance and memory cost."
        ))
    parser.add_argument(
        "pprof",
        type=bool,
        default=True,
        help="linux-only: process collected samples with pprof.")
    return parser

  def __init__(self,
               js=True,
               v8_interpreted_frames=True,
               pprof=True,
               browser_process=False):
    super().__init__()
    self._sample_js = js
    self._sample_browser_process = browser_process
    self._run_pprof = pprof
    self._expose_v8_interpreted_frames = v8_interpreted_frames
    if v8_interpreted_frames:
      assert js, "Cannot expose V8 interpreted frames without js profiling."

  def is_compatible(self, browser):
    if browser.platform.is_linux:
      return isinstance(browser, cb.browsers.Chromium)
    if browser.platform.is_macos:
      return True
    return False

  @property
  def sample_js(self) -> bool:
    return self._sample_js

  @property
  def sample_browser_process(self) -> bool:
    return self._sample_browser_process

  @property
  def run_pprof(self) -> bool:
    return self._run_pprof

  def attach(self, browser: cb.browsers.Browser):
    super().attach(browser)
    if self.browser_platform.is_linux:
      assert isinstance(browser, cb.browsers.Chromium), (
          f"Expected Chromium-based browser, found {type(browser)}.")
      self._attach_linux(browser)

  def pre_check(self, env: cb.env.HostEnvironment):
    super().pre_check(env)
    if self.browser_platform.is_linux:
      env.check_installed(binaries=["pprof"])
      assert self.browser_platform.which("perf"), "Please install linux-perf"
    elif self.browser_platform.is_macos:
      assert self.browser_platform.which(
          "xctrace"), "Please install Xcode to use xctrace"
    if self._run_pprof:
      try:
        self.browser_platform.sh(self.browser_platform.which("gcertstatus"))
        return
      except helper.SubprocessError:
        env.handle_warning("Please run gcert for generating pprof results")
    # Only Linux-perf results can be merged
    if self.browser_platform.is_macos and env.runner.repetitions > 1:
      env.handle_warning(f"Probe={self.NAME} cannot merge data over multiple "
                         f"repetitions={env.runner.repetitions}.")

  def _attach_linux(self, browser: cb.browsers.Chromium):
    if self._sample_js:
      browser.js_flags.update(self.JS_FLAGS_PERF)
      if self._expose_v8_interpreted_frames:
        browser.js_flags.set(self._INTERPRETED_FRAMES_FLAG)
    cmd = pathlib.Path(__file__).parent / "linux-perf-chrome-renderer-cmd.sh"
    assert not self.browser_platform.is_remote, (
        "Copying renderer command prefix to remote platform is "
        "not implemented yet")
    assert cmd.is_file(), f"Didn't find {cmd}"
    browser.flags["--renderer-cmd-prefix"] = str(cmd)
    # Disable sandbox to write profiling data
    browser.flags.set("--no-sandbox")

  def get_scope(self, run: cb.runner.Run):
    if self.browser_platform.is_linux:
      return self.LinuxProfilingScope(self, run)
    if self.browser_platform.is_macos:
      return self.MacOSProfilingScope(self, run)
    raise Exception("Invalid platform")

  class MacOSProfilingScope(base.Probe.Scope):
    _process: subprocess.Popen

    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      self._default_results_file = self.results_file.parent / "profile.trace"

    def start(self, run):
      self._process = self.browser_platform.popen("xctrace", "record",
                                                  "--template", "Time Profiler",
                                                  "--all-processes", "--output",
                                                  self.results_file)
      # xctrace takes some time to start up
      time.sleep(3)

    def stop(self, run: cb.runner.Run):
      # Needs to be SIGINT for xctrace, terminate won't work.
      self._process.send_signal(signal.SIGINT)

    def tear_down(self, run: cb.runner.Run):
      while self._process.poll() is None:
        time.sleep(1)
      return self.results_file

  class LinuxProfilingScope(base.Probe.Scope):
    PERF_DATA_PATTERN = "*.perf.data"
    TEMP_FILE_PATTERNS = (
        "*.perf.data.jitted",
        "jitted-*.so",
        "jit-*.dump",
    )

    def __init__(self, probe: ProfilingProbe, run: cb.runner.Run):
      super().__init__(probe, run)
      self._perf_process = None

    def start(self, run):
      if not self.probe.sample_browser_process:
        return
      if run.browser.pid is None:
        logging.warning("Cannot sample browser process")
        return
      perf_data_file = run.out_dir / "browser.perf.data"
      # TODO: not fully working yet
      self._perf_process = self.browser_platform.popen(
          "perf", "record", "--call-graph=fp", "--freq=max", "--clockid=mono",
          f"--output={perf_data_file}", f"--pid={run.browser.pid}")

    def setup(self, run: cb.runner.Run):
      for probe in run.probes:
        assert not isinstance(probe, cb.probes.v8.V8LogProbe), (
            "Cannot use profiler and v8.log probe in parallel yet")

    def stop(self, run: cb.runner.Run):
      if self._perf_process:
        self._perf_process.terminate()

    def tear_down(self, run: cb.runner.Run):
      # Waiting for linux-perf to flush all perf data
      if self.probe.sample_browser_process:
        time.sleep(3)
      time.sleep(1)

      perf_files = helper.sort_by_file_size(
          run.out_dir.glob(self.PERF_DATA_PATTERN))
      if self.probe.sample_js:
        perf_files = self._inject_v8_symbols(run, perf_files)
      perf_files = helper.sort_by_file_size(perf_files)
      if not self.probe.run_pprof or not self.browser_platform.which("gcert"):
        return map(str, perf_files)

      try:
        urls = self._export_to_pprof(run, perf_files)
      finally:
        self._clean_up_temp_files(run)
      logging.debug("Profiling results: %s", urls)
      return urls

    def _inject_v8_symbols(self, run: cb.runner.Run,
                           perf_files: List[pathlib.Path]):
      with run.actions(f"Probe {self.probe.name}: Injecting V8 Symbols"):
        # Filter out empty files
        perf_files = [file for file in perf_files if file.stat().st_size > 0]
        if self.browser_platform.is_remote:
          # Use loop, as we cannot easily serialize the remote platform.
          perf_jitted_files = [
              linux_perf_probe_inject_v8_symbols(file, self.browser_platform)
              for file in perf_files
          ]
        else:
          assert self.browser_platform == helper.platform
          with multiprocessing.Pool() as pool:
            perf_jitted_files = list(
                pool.imap(linux_perf_probe_inject_v8_symbols, perf_files))
        return [file for file in perf_jitted_files if file is not None]

    def _export_to_pprof(self, run: cb.runner.Run,
                         perf_files: List[pathlib.Path]):
      run_details_json = json.dumps(run.get_browser_details_json())
      with run.actions(f"Probe {self.probe.name}: exporting to pprof"):
        self.browser_platform.sh("gcertstatus >&/dev/null || gcert", shell=True)
        items = zip(perf_files, [run_details_json] * len(perf_files))
        if self.browser_platform.is_remote:
          # Use loop, as we cannot easily serialize the remote platform.
          urls = dict(
              linux_perf_probe_pprof(perf_data_file, run_details,
                                     self.browser_platform)
              for perf_data_file, run_details in items)
        else:
          assert self.browser_platform == helper.platform
          with multiprocessing.Pool() as pool:
            urls = dict(pool.starmap(linux_perf_probe_pprof, items))
        try:
          if perf_files:
            # Make this configurable as it is generally too slow.
            # url = urls["combined"] = self.platform.sh_stdout(
            #     "pprof", "-flame", *perf_files).strip()
            # logging.info("PPROF COMBINED %s", url)
            pass
        except Exception as e:  # pylint: disable=broad-except
          logging.debug("Failed to run pprof: %s", e)
        return urls

    def _clean_up_temp_files(self, run: cb.runner.Run):
      for pattern in self.TEMP_FILE_PATTERNS:
        for file in run.out_dir.glob(pattern):
          file.unlink()


def linux_perf_probe_inject_v8_symbols(
    perf_data_file: pathlib.Path,
    platform: Optional[helper.Platform] = None):
  assert perf_data_file.is_file()
  output_file = perf_data_file.with_suffix(".data.jitted")
  assert not output_file.exists()
  try:
    platform = platform or helper.platform
    platform.sh("perf", "inject", "--jit", f"--input={perf_data_file}",
                f"--output={output_file}")
  except Exception as e:  # pylint: disable=broad-except
    logging.warning("Failed processing: %s\n%s", perf_data_file, e)
    return None
  return output_file


def linux_perf_probe_pprof(perf_data_file: pathlib.Path,
                           run_details: str,
                           platform: Optional[helper.Platform] = None):
  platform = platform or helper.platform
  url = platform.sh_stdout(
      "pprof",
      "-flame",
      f"-add_comment={run_details}",
      perf_data_file,
  ).strip()
  size = helper.get_file_size(perf_data_file)
  logging.info("PPROF")
  logging.info("  linux-perf:   %s %s", perf_data_file.name, size)
  logging.info("  pprof result: %s", url)
  return (
      perf_data_file.stem,
      url,
  )
