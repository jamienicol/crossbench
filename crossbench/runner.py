# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import contextlib
import datetime as dt
import inspect
import logging
import os
import pathlib
import shutil
import sys
import traceback
from typing import Iterable, Sequence, List, Optional, Tuple

import crossbench as cb


class CheckList:

  def __init__(self, runner, platform: Optional[cb.helper.Platform] = None):
    self._runner = runner
    self._wait_until = dt.datetime.now()
    self._platform = platform or cb.helper.platform

  @property
  def runner(self):
    return self._runner

  def _add_min_delay(self, seconds):
    end_time = dt.datetime.now() + dt.timedelta(seconds=seconds)
    if end_time > self._wait_until:
      self._wait_until = end_time

  def _wait_min_time(self):
    delta = self._wait_until - dt.datetime.now()
    if delta <= dt.timedelta(0):
      return
    self._platform.sleep(delta)

  def warn(self, message):
    result = input(
        f"{cb.helper.TTYColor.RED}{message}{cb.helper.TTYColor.RESET} [Yn]")
    return result.lower() != "n"

  def _disable_crowdstrike(self):
    """go/crowdstrike-falcon has quite terrible overhead for each file-access
    disable to prevent flaky numbers """
    if not self._platform.is_macos:
      return True
    try:
      self._platform.disable_monitoring()
      self._add_min_delay(5)
      return True
    except Exception as e:
      logging.exception("Exception: %s", e)
      return self.warn(
          "Could not disable go/crowdstrike-falcon monitor which can cause"
          " high background CPU usage. Continue nevertheless?")

  def _check_disk_space(self):
    # Check the remaining disk space on the FS where we write the results.
    usage = self._platform.disk_usage(self.runner.out_dir)
    free_gib = round(usage.free / 1024 / 1024 / 1024, 2)
    # Warn if there are less than 20GiB
    if free_gib > 20:
      return True
    return self.warn(f"Only {free_gib}GiB disk space left, continue?")

  def _check_power(self):
    # By default we expect users to run on power. However, there are
    # certain probes that require battery power:
    for probe in self._runner.probes:
      if probe.BATTERY_ONLY:
        return True
    if self._platform.is_battery_powered:
      return self.warn("Running on battery power, continue?")
    return True

  def _check_cpu_usage(self):
    cpu_usage_percent = round(100 * self._platform.cpu_usage(), 1)
    if cpu_usage_percent < 20:
      return True
    return self.warn(f"CPU usage is high ({cpu_usage_percent}%), continue?")

  def _check_cpu_temperature(self):
    cpu_speed = self._platform.get_relative_cpu_speed()
    if cpu_speed == 1:
      return True
    return self.warn(
        f"CPU thermal throttling is active (relative speed is {cpu_speed})."
        " Continue?")

  def _check_cpu_power_mode(self):
    # TODO Implement checks for performance mode
    return True

  def _check_running_binaries(self):
    ps_stats = self._platform.sh_stdout("ps", "aux")
    browser_binaries = cb.helper.group_by(
        self.runner.browsers, key=lambda browser: str(browser.path))
    for binary, browsers in browser_binaries.items():
      # Add a white-space to get less false-positives
      binary_search = f"{binary} "
      filtered = tuple(line for line in ps_stats.splitlines() if binary in line)
      if len(filtered) == 0:
        continue
      # Use the first in the group
      browser = browsers[0]
      logging.debug("Binary=%s", binary)
      logging.debug("PS status output:")
      logging.debug(filtered)
      result = self.warn(
          f"{browser.app_name} {browser.version} seems to be already running. "
          "Continue?")
      if not result:
        return False
    return True

  def _check_headless(self):
    if self._platform.is_win:
      return True
    # We only have a $DISPLAY env var on macos if xquartz is installed
    if self._platform.is_macos:
      return True
    if os.environ.get("DISPLAY", None) is not None:
      return True
    for browser in self._runner.browsers:
      if browser.is_headless:
        continue
      if not self.warn(
          f"Browser {browser.short_name} will likely not work in headless mode."
          "Continue?"):
        return False
    return True

  def _check_probes(self):
    if not self._runner.probes:
      return self.warn("No probes specified. Continue?")
    for probe in self._runner.probes:
      if not probe.pre_check(self):
        return False
    return True

  def is_ok(self) -> bool:
    ok = True
    ok &= self._disable_crowdstrike()
    ok &= self._check_power()
    ok &= self._check_disk_space()
    ok &= self._check_cpu_usage()
    ok &= self._check_cpu_temperature()
    ok &= self._check_cpu_power_mode()
    ok &= self._check_running_binaries()
    ok &= self._check_headless()
    ok &= self._check_probes()
    self._wait_min_time()
    return ok

  def check_installed(self, binaries, message="Missing binaries: %s"):
    missing = (binary for binary in binaries if not shutil.which(binary))
    if missing:
      return self.warn((message % binaries) + " Continue?")


class ExceptionHandler:

  _exceptions: List[Tuple[str, BaseException]]
  throw: bool

  def __init__(self, throw=False):
    self._exceptions = []
    self.throw = throw

  @property
  def is_success(self) -> bool:
    return len(self._exceptions) == 0

  @property
  def exceptions(self):
    return self._exceptions

  def extend(self, handler: ExceptionHandler):
    self._exceptions.extend(handler.exceptions)

  def handle(self, e: BaseException):
    if isinstance(e, KeyboardInterrupt):
      sys.exit(0)
    # TODO: Log acton stacks / state for easier debugging
    tb = traceback.format_exc()
    self._exceptions.append((tb, e))
    logging.info("Intermediate Exception: %s", e)
    logging.info(tb)
    if self.throw:
      raise

  def print(self):
    logging.error("ERRORS occurred")
    for tb, exception in self._exceptions:
      logging.error(tb)
    for tb, exception in self._exceptions:
      logging.error(exception)

  def to_json(self) -> list:
    return [dict(title=str(e), trace=str(tb)) for tb, e in self._exceptions]


class Runner:
  @staticmethod
  def get_out_dir(cwd, suffix="", test=False) -> pathlib.Path:
    if test:
      return cwd / "results" / "test"
    if suffix:
      suffix = "_" + suffix
    return (cwd / "results" /
            f"{dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')}{suffix}")

  @classmethod
  def add_cli_parser(cls, parser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--repeat",
        default=1,
        type=int,
        help="Number of times each benchmark story is "
        "repeated. Defaults to 1")
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        help="Results will be stored in this directory. "
        "Defaults to result/$DATE")
    parser.add_argument(
        "--throw",
        action="store_true",
        default=False,
        help="Directly throw exceptions")
    parser.add_argument("--label", type=str, help="Custom output label")
    parser.add_argument(
        "--skip-checklist",
        dest="use_checklist",
        action="store_false",
        default=True,
        help="Do not check for potential SetUp issues "
        "before running the benchmark. Enabled by default.")
    return parser

  @classmethod
  def kwargs_from_cli(cls, args):
    if args.out_dir is None:
      label = args.label or args.benchmark_cls.NAME
      cli_dir = pathlib.Path(__file__).parent.parent
      args.out_dir = cls.get_out_dir(cli_dir, label)
    return dict(
        out_dir=args.out_dir,
        browsers=args.browsers,
        repetitions=args.repeat,
        use_checklist=args.use_checklist,
        throw=args.throw)


  def __init__(self,
               out_dir: pathlib.Path,
               browsers: Sequence[cb.browsers.Browser],
               benchmark: cb.benchmarks.Benchmark,
               additional_probes: Iterable[cb.probes.Probe] = (),
               platform: cb.helper.Platform = cb.helper.platform,
               throttle=True,
               repetitions=1,
               use_checklist=True,
               throw=False):
    self.out_dir = out_dir
    assert not self.out_dir.exists(), f"out_dir={self.out_dir} exists already"
    self.out_dir.mkdir(parents=True)
    self.default_wait = 2 if throttle else 0.1
    self.browsers = browsers
    self._validate_browsers()
    self._browser_platform = browsers[0].platform
    self.stories = benchmark.stories
    self.repetitions = repetitions
    assert self.repetitions > 0, f"Invalid repetitions={self.repetitions}"
    self.throttle = throttle
    self._use_checklist = use_checklist
    self._probes = []
    self._runs = []
    self._exceptions = ExceptionHandler(throw)
    self._platform = platform
    self._attach_default_probes(additional_probes)
    self._validate_stories()

  def _validate_stories(self):
    for probe_cls in self.stories[0].PROBES:
      assert inspect.isclass(probe_cls), (
          f"Story.PROBES must contain classes only, but got {type(probe_cls)}")
      self.attach_probe(probe_cls())

  def _validate_browsers(self):
    assert self.browsers, "No browsers provided"
    browser_labels = [browser.label for browser in self.browsers]
    assert len(browser_labels) == len(
        set(browser_labels)), (f"Duplicated browser labels in {browser_labels}")
    browser_platforms = set(browser.platform for browser in self.browsers)
    assert len(browser_platforms) == 1, (
        "Browsers running on multiple platforms are not supported: "
        f"platforms={browser_platforms} browsers={self.browsers}")

  def _attach_default_probes(self, probe_list: Iterable[cb.probes.Probe]):
    assert len(self._probes) == 0
    self.attach_probe(cb.probes.RunResultsSummaryProbe())
    self.attach_probe(cb.probes.RunDurationsProbe())
    self.attach_probe(cb.probes.RunRunnerLogProbe())
    for probe in probe_list:
      self.attach_probe(probe)

  def attach_probe(self, probe: cb.probes.Probe, matching_browser_only=False):
    assert isinstance(probe, cb.probes.Probe), (
        f"Probe must be an instance of Probe, but got {type(probe)}.")
    assert probe not in self._probes, "Cannot add the same probe twice"
    self._probes.append(probe)
    for browser in self.browsers:
      if not probe.is_compatible(browser):
        if matching_browser_only:
          logging.warning("Skipping incompatible probe=%s for browser=%s",
                          probe.name, browser.short_name)
          continue
        raise Exception(f"Probe '{probe.name}' is not compatible with browser "
                        f"{browser.type}")
      browser.attach_probe(probe)
    return probe

  @property
  def probes(self) -> List[cb.probes.Probe]:
    return list(self._probes)

  @property
  def exceptions(self) -> ExceptionHandler:
    return self._exceptions

  @property
  def is_success(self) -> bool:
    return len(self._runs) > 0 and self._exceptions.is_success

  @property
  def platform(self) -> cb.helper.Platform:
    return self._platform

  @property
  def browser_platform(self) -> cb.helper.Platform:
    return self._browser_platform

  def sh(self, *args, shell=False, stdout=None):
    return self._platform.sh(*args, shell=shell, stdout=stdout)

  def wait(self, seconds):
    self._platform.sleep(seconds)

  def collect_hardware_details(self):
    with (self.out_dir / "GetHardwareDetails.details.txt").open("w") as f:
      details = self._platform.get_hardware_details()
      f.write(details)

  def _setup(self):
    if self.repetitions <= 0:
      raise Exception(f"Invalid repetitions count: {self.repetitions}")
    if len(self.browsers) == 0:
      raise Exception("No browsers provided: self.browsers is empty")
    if len(self.stories) == 0:
      raise Exception("No stories provided: self.stories is empty")
    for browser in self.browsers:
      browser.setup_binary(self)  # pytype: disable=wrong-arg-types
    self._runs = list(self.get_runs())
    assert self._runs, "get_runs() produced no runs"
    if self._use_checklist:
      if not CheckList(self, self.browser_platform).is_ok():
        raise Exception("Thou shalt not fail the CheckList")
    self.collect_hardware_details()

  def get_runs(self) -> Iterable[Run]:
    for iteration in range(self.repetitions):
      for story in self.stories:
        for browser in self.browsers:
          yield Run(
              self,
              browser,
              story,
              iteration,
              self.out_dir,
              throw=self._exceptions.throw)

  def run(self, is_dry_run=False):
    try:
      with cb.helper.SystemSleepPreventer():
        self._setup()
        for run in self._runs:
          run.run(is_dry_run)
          self._exceptions.extend(run.exceptions)
        if not is_dry_run:
          self._tear_down()
        logging.info("RESULTS DIR: %s", self.out_dir)
        if not self.is_success:
          self._exceptions.print()
          raise Exception("Runs failed")
    except KeyboardInterrupt:
      # Fast exit in case without a stacktrace for better usability
      pass

  def _tear_down(self):
    logging.info("MERGING PROBE DATA: iterations")
    throw = self._exceptions.throw
    repetitions_groups = RepetitionsRunGroup.groups(self._runs, throw)
    for repetitions_group in repetitions_groups:
      repetitions_group.merge(self)
      self._exceptions.extend(repetitions_group.exceptions)
    logging.info("MERGING PROBE DATA: stories")
    story_groups = StoriesRunGroup.groups(repetitions_groups, throw)
    for story_group in story_groups:
      story_group.merge(self)
      self._exceptions.extend(story_group.exceptions)
    logging.info("MERGING PROBE DATA: browsers")
    browser_group = BrowsersRunGroup(story_groups, throw)
    browser_group.merge(self)
    self._exceptions.extend(browser_group.exceptions)

  def cool_down(self, default_wait=None):
    # Cool down between runs
    default_wait = default_wait or self.default_wait
    self.wait(default_wait)
    if not self._platform.is_thermal_throttled():
      return
    logging.info("COOLDOWN")
    for time_spent, time_left in cb.helper.wait_with_backoff(
        cb.helper.wait_range(1, 100)):
      if not self._platform.is_thermal_throttled():
        break
      logging.info("COOLDOWN: still hot, waiting some more")



class RunGroup:

  def __init__(self, throw=False):
    self._exceptions = ExceptionHandler(throw)
    self._path = None
    self._merged_probe_results = None

  def _set_path(self, path: pathlib.Path):
    assert self._path is None
    self._path = path
    self._merged_probe_results = cb.probes.ProbeResultDict(path)

  @property
  def results(self) -> cb.probes.ProbeResultDict:
    return self._merged_probe_results

  @property
  def path(self) -> pathlib.Path:
    return self._path

  @property
  def exceptions(self) -> ExceptionHandler:
    return self._exceptions

  def get_probe_results_file(self, probe: cb.probes.Probe) -> pathlib.Path:
    new_file = self.path / probe.results_file_name
    assert not new_file.exists(), (
        f"Merged file {new_file} for {self.__class__} exists already.")
    return new_file

  def merge(self, runner: Runner):
    for probe in reversed(runner.probes):
      try:
        results = self._merge_probe_results(probe)
        if results is None:
          continue
        self._merged_probe_results[probe] = results
      except Exception as e:
        self._exceptions.handle(e)

  def _merge_probe_results(self, probe: cb.probes.Probe):
    return None


class RepetitionsRunGroup(RunGroup):
  """
  A group of Run objects that are different repetitions for the same Story with
  and the same browser.
  """

  @classmethod
  def groups(cls, runs, throw=False):
    return list(
        cb.helper.group_by(
            runs,
            key=lambda run: (run.story, run.browser),
            group=lambda _: cls(throw)).values())

  def __init__(self, throw=False):
    super().__init__(throw)
    self._runs = []
    self._story: cb.stories.Story = None
    self._browser: cb.browsers.Browser = None

  def append(self, run):
    if self._path is None:
      self._set_path(run.group_dir)
      self._story = run.story
      self._browser = run.browser
    assert self._story == run.story
    assert self._path == run.group_dir
    assert self._browser == run.browser
    self._runs.append(run)

  @property
  def runs(self) -> Iterable[Run]:
    return self._runs

  @property
  def story(self) -> cb.stories.Story:
    return self._story

  @property
  def browser(self) -> cb.browsers.Browser:
    return self._browser

  def _merge_probe_results(self, probe: cb.probes.Probe):
    return probe.merge_repetitions(self)  # pytype: disable=wrong-arg-types


class StoriesRunGroup(RunGroup):
  """
  A group of StoryRepetitionsRunGroups for the same browser.
  """

  def __init__(self, throw=False):
    super().__init__(throw)
    self._repetitions_groups: List[RepetitionsRunGroup] = []
    self._browser: cb.browsers.Browser = None

  @classmethod
  def groups(cls, run_groups, throw=False):
    return list(
        cb.helper.group_by(
            run_groups,
            key=lambda run_group: run_group.browser,
            group=lambda _: cls(throw)).values())

  def append(self, group: RepetitionsRunGroup):
    if self._path is None:
      self._set_path(group.path.parent)
      self._browser = group.browser
    assert self._path == group.path.parent
    assert self._browser == group.browser
    self._repetitions_groups.append(group)

  @property
  def repetitions_groups(self) -> List[RepetitionsRunGroup]:
    return self._repetitions_groups

  @property
  def runs(self) -> Iterable[Run]:
    for group in self._repetitions_groups:
      yield from group.runs

  @property
  def browser(self) -> cb.browsers.Browser:
    return self._browser

  @property
  def stories(self) -> Iterable[cb.stories.Story]:
    return (group.story for group in self._repetitions_groups)

  def _merge_probe_results(self, probe: cb.probes.Probe):
    return probe.merge_stories(self)  # pytype: disable=wrong-arg-types


class BrowsersRunGroup(RunGroup):
  _story_groups: Iterable[StoriesRunGroup]

  def __init__(self, story_groups, throw):
    super().__init__(throw)
    self._story_groups = story_groups
    self._set_path(story_groups[0].path.parent)

  @property
  def story_groups(self) -> Iterable[StoriesRunGroup]:
    return self._story_groups

  @property
  def repetitions_groups(self) -> Iterable[RepetitionsRunGroup]:
    for story_group in self._story_groups:
      yield from story_group.repetitions_groups

  @property
  def runs(self) -> Iterable[Run]:
    for group in self._story_groups:
      yield from group.runs

  def _merge_probe_results(self, probe: cb.probes.Probe):
    return probe.merge_browsers(self)  # pytype: disable=wrong-arg-types


class Run:
  STATE_INITIAL = 0
  STATE_PREPARE = 1
  STATE_RUN = 2
  STATE_DONE = 3

  def __init__(self,
               runner: Runner,
               browser: cb.browsers.Browser,
               story: cb.stories.Story,
               iteration: int,
               root_dir: pathlib.Path,
               name: Optional[str] = None,
               temperature: Optional[int] = None,
               throw=False):
    self._state = self.STATE_INITIAL
    self._run_success = None
    self._runner = runner
    self._browser = browser
    self._story = story
    self._iteration = iteration
    self._name = name
    self._out_dir = self.get_out_dir(root_dir).absolute()
    self._probe_results = cb.probes.ProbeResultDict(self._out_dir)
    self._extra_js_flags = cb.flags.JSFlags()
    self._extra_flags = cb.flags.Flags()
    self._durations = cb.helper.Durations()
    self._temperature = temperature
    self._exceptions = ExceptionHandler(throw)

  def get_out_dir(self, root_dir) -> pathlib.Path:
    return root_dir / self.browser.short_name / self.story.name / str(
        self._iteration)

  @property
  def group_dir(self) -> pathlib.Path:
    return self.out_dir.parent

  def actions(self, name) -> Actions:
    return Actions(name, self)

  @property
  def temperature(self):
    return self._temperature

  @property
  def durations(self) -> cb.helper.Durations:
    return self._durations

  @property
  def iteration(self) -> int:
    return self._iteration

  @property
  def runner(self) -> Runner:
    return self._runner

  @property
  def browser(self) -> cb.browsers.Browser:
    return self._browser

  @property
  def platform(self) -> cb.helper.Platform:
    return self._browser.platform

  @property
  def story(self) -> cb.stories.Story:
    return self._story

  @property
  def name(self) -> Optional[str]:
    return self._name

  @property
  def extra_js_flags(self) -> cb.flags.JSFlags:
    return self._extra_js_flags

  @property
  def out_dir(self) -> pathlib.Path:
    return self._out_dir

  @property
  def extra_flags(self) -> cb.flags.Flags:
    return self._extra_flags

  @property
  def probes(self) -> Iterable[cb.probes.Probe]:
    return self._runner.probes

  @property
  def results(self) -> cb.probes.ProbeResultDict:
    return self._probe_results

  @property
  def exceptions(self) -> ExceptionHandler:
    return self._exceptions

  @property
  def is_success(self) -> bool:
    return self._exceptions.is_success

  def get_browser_details_json(self) -> dict:
    details_json = self.browser.details_json()
    details_json["js_flags"] += tuple(self.extra_js_flags.get_list())
    details_json["flags"] += tuple(self.extra_flags.get_list())
    return details_json

  def get_probe_results_file(self, probe: cb.probes.Probe) -> pathlib.Path:
    file = self._out_dir / probe.results_file_name
    assert not file.exists(), f"Probe results file exists already. file={file}"
    return file

  def setup(self):
    logging.info("PREPARE")
    self._advance_state(self.STATE_INITIAL, self.STATE_PREPARE)
    self._run_success = None
    browser_log_file = self._out_dir / "browser.log"
    assert not browser_log_file.exists(), (
        f"Default browser log file {browser_log_file} already exists.")
    self._browser.set_log_file(browser_log_file)

    with self._durations.measure("runner-cooldown"):
      # self._runner.cool_down()
      self._runner.wait(self._runner.default_wait)

    probe_run_scopes = []
    with self._durations.measure("probes-creation"):
      probe_set = set()
      for probe in self.probes:
        assert probe not in probe_set, (
            f"Got duplicate probe name={probe.name}")
        probe_set.add(probe)
        if probe.PRODUCES_DATA:
          self._probe_results[probe] = None
        probe_run_scopes.append(probe.get_scope(self))

    with self._durations.measure("probes-setup"):
      for probe_scope in probe_run_scopes:
        probe_scope.setup(self)

    with self._durations.measure("browser-setup"):
      try:
        # pytype somehow gets the package path wrong here, disabling for now.
        self._browser.setup(self)  # pytype: disable=wrong-arg-types
      except:
        # Clean up half-setup browser instances
        self._browser.force_quit()
        raise
    return probe_run_scopes

  def run(self, is_dry_run=False):
    if is_dry_run:
      # TODO(cbruni): Implement better logging for dry-runs
      return
    self._out_dir.mkdir(parents=True, exist_ok=True)
    with cb.helper.ChangeCWD(self._out_dir):
      probe_scopes = self.setup()
      self._advance_state(self.STATE_PREPARE, self.STATE_RUN)
      self._run_success = False
      logging.debug("CWD %s", self._out_dir)
      try:
        probe_start_time = dt.datetime.now()
        probe_scope_manager = contextlib.ExitStack()
        for probe_scope in probe_scopes:
          probe_scope.set_start_time(probe_start_time)
          probe_scope_manager.enter_context(probe_scope)
        with probe_scope_manager:
          self._durations["probes-start"] = (
              dt.datetime.now() - probe_start_time)
          logging.info("RUN: BROWSER=%s STORY=%s", self._browser.short_name,
                       self.story.name)
          assert self._state == self.STATE_RUN, "Invalid state"
          with self._durations.measure("run"):
            self._story.run(self)
          self._run_success = True
      except Exception as e:
        self._exceptions.handle(e)
      finally:
        self.tear_down(probe_scopes)

  def _advance_state(self, expected, next):
    assert self._state == expected, (
        f"Invalid state got={self._state} expected={expected}")
    self._state = next

  def tear_down(self, probe_scopes, is_shutdown=False):
    self._advance_state(self.STATE_RUN, self.STATE_DONE)
    with self._durations.measure("browser-TearDown"):
      if is_shutdown:
        try:
          self._browser.quit(self._runner)
        except Exception as e:
          logging.warning("Error quitting browser: %s", e)
          return
      try:
        self._browser.quit(self._runner)
      except Exception as e:
        logging.warning("Error quitting browser: %s", e)
        self._exceptions.handle(e)
    with self._durations.measure("probes-TearDown"):
      logging.info("TEARDOWN")
      self._tear_down_probe_scopes(probe_scopes)

  def _tear_down_probe_scopes(self, probe_scopes):
    for probe_scope in reversed(probe_scopes):
      try:
        assert probe_scope.run == self
        probe_results = probe_scope.tear_down(self)
        probe = probe_scope.probe
        if probe_results is None:
          logging.warning("Probe did not extract any data. probe=%s run=%s",
                          probe, self)
        self._probe_results[probe] = probe_results
      except Exception as e:
        self._exceptions.handle(e)


class Actions(cb.helper.TimeScope):
  _run: Run
  _browser: cb.browsers.Browser
  _runner: Runner
  _parent: Actions
  _is_active: bool = False

  def __init__(self, message, run: Run, runner=None, browser=None, parent=None):
    assert message, "Actions need a name"
    super().__init__(message)
    self._run = run
    self._browser = browser or (run and run.browser)
    self._runner = runner or run.runner
    self._parent = parent

  @property
  def run(self) -> Run:
    return self._run

  @property
  def platform(self) -> cb.helper.Platform:
    return self._run.platform

  def __enter__(self):
    super().__enter__()
    self._is_active = True
    logging.info("ACTION START %s", self._message)
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    self._is_active = False
    logging.info("ACTION END %s", self._message)
    super().__exit__(exc_type, exc_value, exc_traceback)

  def _assert_is_active(self):
    assert self._is_active, "Actions have to be used in a with scope"

  def js(self, js_code: str, timeout=10, arguments=(), **kwargs):
    self._assert_is_active()
    assert js_code, "js_code must be a valid JS script"
    if kwargs:
      js_code = js_code.format(**kwargs)
    return self._browser.js(self._runner, js_code, timeout, arguments=arguments)

  def wait_js_condition(self, js_code: str, wait_range):
    assert "return" in js_code, (
        f"Missing return statement in js-wait code: {js_code}")
    for time_spent, time_left in cb.helper.wait_with_backoff(wait_range):
      result = self.js(js_code, timeout=time_left)
      if result:
        return time_spent
      assert result is False, (
          f"js_code did not return a bool, but got: {result}")

  def navigate_to(self, url: str):
    self._assert_is_active()
    self._browser.show_url(self._runner, url)

  def wait(self, seconds=1):
    self._assert_is_active()
    self.platform.sleep(seconds)
