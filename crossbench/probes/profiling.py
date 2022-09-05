# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import multiprocessing
import shutil
import signal
import time
import pathlib

from crossbench import helper, probes


class ProfilingProbe(probes.Probe):
  """
  General-purpose sampling profiling probe.

  Implementation:
  - Uses linux-perf on linux platforms (per browser/renderer process)
  - Uses xctrace on MacOS (currently only system-wide)

  For linux-based Chromium browsers it also injects JS stack samples with names
  from V8. For Googlers it additionally it can auto-uploads symbolized profiles
  to pprof.
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
    if helper.platform.is_linux:
      return browser.type == "chrome"
    if helper.platform.is_macos:
      return True
    return False

  def attach(self, browser):
    super().attach(browser)
    if helper.platform.is_linux:
      self._attach_linux(browser)

  def pre_check(self, checklist):
    if not super().pre_check(checklist):
      return False
    if helper.platform.is_linux:
      assert shutil.which("pprof"), "Please install pprof"
    elif helper.platform.is_macos:
      assert shutil.which("xctrace"), "Please install Xcode to use xctrace"
    if self._run_pprof:
      try:
        helper.platform.sh(shutil.which("gcertstatus"))
        return True
      except helper.SubprocessError:
        return checklist.warn("Please run gcert for generating pprof results")
    # Only Linux-perf results can be merged
    if helper.platform.is_macos and checklist.runner.repetitions > 1:
      return checklist.warn(
          f"Probe={self.NAME} cannot merge data over multiple "
          f"repetitions={checklist.runner.repetitions}. Continue?")
    return True

  def _attach_linux(self, browser):
    if self._sample_js:
      browser.js_flags.update(self.JS_FLAGS_PERF)
    cmd = pathlib.Path(__file__).parent / "linux-perf-chrome-renderer-cmd.sh"
    assert cmd.is_file(), f"Didn't find {cmd}"
    browser.flags["--renderer-cmd-prefix"] = str(cmd)
    # Disable sandbox to write profiling data
    browser.flags.set("--no-sandbox")

  def get_scope(self, run):
    if helper.platform.is_linux:
      return self.LinuxProfilingScope(self, run)
    if helper.platform.is_macos:
      return self.MacOSProfilingScope(self, run)
    raise Exception("Invalid platform")

  class MacOSProfilingScope(probes.Probe.Scope):

    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      self._default_results_file = self.results_file.parent / "profile.trace"

    def start(self, run):
      self._process = helper.platform.popen("xctrace", "record", "--template",
                                            "Time Profiler", "--all-processes",
                                            "--output", self.results_file)
      # xctrace takes some time to start up
      time.sleep(3)

    def stop(self, run):
      # Needs to be SIGINT for xctrace, terminate won"t work.
      self._process.send_signal(signal.SIGINT)

    def tear_down(self, run):
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

    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      self._perf_process = None

    def start(self, run):
      if not self.probe._sample_browser_process:
        return
      if run.browser.pid is None:
        logging.warning("Cannot sample browser process")
        return
      perf_data_file = run.out_dir / "browser.perf.data"
      # TODO: not fully working yet
      self._perf_process = helper.platform.popen("perf", "record",
                                                 "--call-graph=fp",
                                                 "--freq=max", "--clockid=mono",
                                                 f"--output={perf_data_file}",
                                                 f"--pid={run.browser.pid}")

    def stop(self, run):
      if self._perf_process:
        self._perf_process.terminate()

    def tear_down(self, run):
      # Waiting for linux-perf to flush all perf data
      if self.probe._sample_browser_process:
        time.sleep(3)
      time.sleep(1)

      perf_files = helper.sort_by_file_size(
          run.out_dir.glob(self.PERF_DATA_PATTERN))
      if self.probe._sample_js:
        perf_files = self._inject_v8_symbols(run, perf_files)
      perf_files = helper.sort_by_file_size(perf_files)
      if not self.probe._run_pprof or not shutil.which("gcert"):
        return map(str, perf_files)

      try:
        urls = self._export_to_pprof(run, perf_files)
      finally:
        self._clean_up_temp_files(run)
      logging.debug(f"Profliling results: {urls}")
      return urls

    def _inject_v8_symbols(self, run, perf_files):
      with run.actions(f"Probe {self.probe.name}: Injecting V8 Symbols"):
        # Filter out empty files
        perf_files = (file for file in perf_files if file.stat().st_size > 0)
        with multiprocessing.Pool() as pool:
          perf_jitted_files = list(
              pool.imap(linux_perf_probe_inject_v8_symbols, perf_files))
        return list(file for file in perf_jitted_files if file is not None)

    def _export_to_pprof(self, run, perf_files):
      run_details_json = run.get_browser_details_json()
      with run.actions(f"Probe {self.probe.name}: exporting to pprof"):
        helper.platform.sh("gcertstatus >&/dev/null || gcert", shell=True)
        with multiprocessing.Pool() as pool:
          items = zip(perf_files, [run_details_json] * len(perf_files))
          urls = dict(pool.starmap(linux_perf_probe_pprof, items))
        try:
          if perf_files:
            # Make this configurable as it is generally too slow.
            # url = urls["combined"] = helper.platform.sh_stdout(
            #     "pprof", "-flame", *perf_files).strip()
            # logging.info(f"PPROF COMBINED {url}")
            pass
        except Exception:
          pass
        return urls

    def _clean_up_temp_files(self, run):
      for pattern in self.TEMP_FILE_PATTERNS:
        for file in run.out_dir.glob(pattern):
          file.unlink()


def linux_perf_probe_inject_v8_symbols(perf_data_file):
  assert perf_data_file.is_file()
  output_file = perf_data_file.with_suffix(".data.jitted")
  assert not output_file.exists()
  try:
    helper.platform.sh("perf", "inject", "--jit", f"--input={perf_data_file}",
                       f"--output={output_file}")
  except Exception:
    logging.warning(f"Failed processing: {perf_data_file}")
    return None
  return output_file


def linux_perf_probe_pprof(perf_data_file, run_details):
  url = helper.platform.sh_stdout(
      "pprof",
      "-flame",
      f"-add_comment={run_details}",
      perf_data_file,
  ).strip()
  size = helper.get_file_size(perf_data_file)
  logging.info("PPROF")
  logging.info(f"  linux-perf:   {perf_data_file.name} {size}")
  logging.info(f"  pprof result: {url}")
  return (
      perf_data_file.stem,
      url,
  )
