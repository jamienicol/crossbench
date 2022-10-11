# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import multiprocessing
import signal
import time
import pathlib
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
  import crossbench as cb
import crossbench.probes as probes


class ProfilingProbe(probes.Probe):
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

  JS_FLAGS_PERF = ("--perf-prof", "--no-write-protect-code-memory",
                   "--interpreted-frames-native-stack")
  IS_GENERAL_PURPOSE = True

  def __init__(self,
               js=True,
               pprof=True,
               browser_process=False,
               *args,
               **kwargs):
    super().__init__(*args, **kwargs)
    self._sample_js = js
    self._sample_browser_process = browser_process
    self._run_pprof = pprof

  def is_compatible(self, browser):
    if browser.platform.is_linux:
      return browser.type == "chrome"
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
      assert isinstance(browser, cb.browsers.Chrome), (
          f"Expected Chrome, found {type(browser)}.")
      self._attach_linux(browser)

  def pre_check(self, checklist: cb.runner.CheckList):
    if not super().pre_check(checklist):
      return False
    if self.browser_platform.is_linux:
      assert self.browser_platform.which("pprof"), "Please install pprof"
    elif self.browser_platform.is_macos:
      assert self.browser_platform.which(
          "xctrace"), "Please install Xcode to use xctrace"
    if self._run_pprof:
      try:
        self.browser_platform.sh(self.browser_platform.which("gcertstatus"))
        return True
      except cb.helper.SubprocessError:
        return checklist.warn("Please run gcert for generating pprof results")
    # Only Linux-perf results can be merged
    if self.browser_platform.is_macos and checklist.runner.repetitions > 1:
      return checklist.warn(
          f"Probe={self.NAME} cannot merge data over multiple "
          f"repetitions={checklist.runner.repetitions}. Continue?")
    return True

  def _attach_linux(self, browser: cb.browsers.Chrome):
    if self._sample_js:
      browser.js_flags.update(self.JS_FLAGS_PERF)
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

  class MacOSProfilingScope(probes.Probe.Scope):

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

  class LinuxProfilingScope(probes.Probe.Scope):
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
      if not self.probe._sample_browser_process:
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
        assert not isinstance(probe, probes.v8.V8LogProbe), (
            "Cannot use profiler and v8.log probe in parallel yet")

    def stop(self, run: cb.runner.Run):
      if self._perf_process:
        self._perf_process.terminate()

    def tear_down(self, run: cb.runner.Run):
      # Waiting for linux-perf to flush all perf data
      if self.probe.sample_browser_process:
        time.sleep(3)
      time.sleep(1)

      perf_files = cb.helper.sort_by_file_size(
          run.out_dir.glob(self.PERF_DATA_PATTERN))
      if self.probe.sample_js:
        perf_files = self._inject_v8_symbols(run, perf_files)
      perf_files = cb.helper.sort_by_file_size(perf_files)
      if not self.probe.run_pprof or not self.browser_platform.which("gcert"):
        return map(str, perf_files)

      try:
        urls = self._export_to_pprof(run, perf_files)
      finally:
        self._clean_up_temp_files(run)
      logging.debug("Profliling results: %s", urls)
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
          assert self.browser_platform == cb.helper.platform
          with multiprocessing.Pool() as pool:
            perf_jitted_files = list(pool.imap(linux_perf_probe_inject_v8_symbols,
                                          perf_files))
        return [file for file in perf_jitted_files if file is not None]

    def _export_to_pprof(self, run: cb.runner.Run,
                         perf_files: List[pathlib.Path]):
      run_details_json = run.get_browser_details_json()
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
          assert self.browser_platform == cb.helper.platform
          with multiprocessing.Pool() as pool:
            urls = dict(pool.starmap(linux_perf_probe_pprof, items))
        try:
          if perf_files:
            # Make this configurable as it is generally too slow.
            # url = urls["combined"] = self.platform.sh_stdout(
            #     "pprof", "-flame", *perf_files).strip()
            # logging.info("PPROF COMBINED %s", url)
            pass
        except Exception:
          pass
        return urls

    def _clean_up_temp_files(self, run: cb.runner.Run):
      for pattern in self.TEMP_FILE_PATTERNS:
        for file in run.out_dir.glob(pattern):
          file.unlink()


def linux_perf_probe_inject_v8_symbols(
    perf_data_file: pathlib.Path,
    platform: Optional[cb.helper.Platform] = None):
  assert perf_data_file.is_file()
  output_file = perf_data_file.with_suffix(".data.jitted")
  assert not output_file.exists()
  try:
    platform = platform or cb.helper.platform
    platform.sh("perf", "inject", "--jit", f"--input={perf_data_file}",
                f"--output={output_file}")
  except Exception:
    logging.warning("Failed processing: %s", perf_data_file)
    return None
  return output_file


def linux_perf_probe_pprof(perf_data_file: pathlib.Path,
                           run_details: str,
                           platform: Optional[cb.helper.Platform] = None):
  platform = platform or cb.helper.platform
  url = platform.sh_stdout(
      "pprof",
      "-flame",
      f"-add_comment={run_details}",
      perf_data_file,
  ).strip()
  size = cb.helper.get_file_size(perf_data_file)
  logging.info("PPROF")
  logging.info("  linux-perf:   %s %s", perf_data_file.name, size)
  logging.info("  pprof result: %s", url)
  return (
      perf_data_file.stem,
      url,
  )
