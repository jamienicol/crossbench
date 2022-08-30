# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import argparse
import contextlib
from datetime import datetime
from datetime import timedelta
import inspect
import logging
import os
from pathlib import Path
import sys
import traceback
import shutil
from typing import Iterable, List, Optional, Type, Tuple, cast

import psutil

import crossbench
from crossbench import browsers, helper, probes, stories, flags


class CheckList:

  def __init__(self, runner):
    self._runner = runner
    self._wait_until = datetime.now()

  @property
  def runner(self):
    return self._runner

  def _add_min_delay(self, seconds):
    end_time = datetime.now() + timedelta(seconds=seconds)
    if end_time > self._wait_until:
      self._wait_until = end_time

  def _wait_min_time(self):
    delta = self._wait_until - datetime.now()
    if delta <= timedelta(0):
      return
    helper.platform.sleep(delta)

  def warn(self, message):
    result = input(
        f"{helper.TTYColor.RED}{message}{helper.TTYColor.RESET} [Yn]")
    return result.lower() != 'n'

  def _disable_crowdstrike(self):
    """go/crowdstrike-falcon has quite terrible overhead for each file-access
    disable to prevent flaky numbers """
    if not helper.platform.is_macos:
      return True
    try:
      helper.platform.disable_monitoring()
      self._add_min_delay(5)
      return True
    except Exception as e:
      logging.exception("Exception: %s", e)
      return self.warn(
          "Could not disable go/crowdstrike-falcon monitor which can cause"
          " high background CPU usage. Continue nevertheless?")

  def _check_disk_space(self):
    # Check the remaining disk space on the FS where we write the results.
    usage = psutil.disk_usage(self.runner.out_dir)
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
    if helper.platform.is_battery_powered:
      return self.warn("Running on battery power, continue?")
    return True

  def _check_cpu_usage(self):
    cpu_usage_percent = round(100 - psutil.cpu_times_percent().idle, 1)
    if cpu_usage_percent < 20:
      return True
    return self.warn(f"CPU usage is high ({cpu_usage_percent}%), continue?")

  def _check_cpu_temperature(self):
    cpu_speed = helper.platform.get_relative_cpu_speed()
    if cpu_speed == 1:
      return True
    return self.warn(
        f"CPU thermal throttling is active (relative speed is {cpu_speed})."
        " Continue?")

  def _check_cpu_power_mode(self):
    # TODO Implement checks for performance mode
    return True

  def _check_running_binaries(self):
    ps_stats = helper.platform.sh_stdout("ps", "aux")
    browser_binaries = helper.group_by(
        self.runner.browsers, key=lambda browser: str(browser.path))
    for binary, browsers in browser_binaries.items():
      # Add a white-space to get less false-positives
      binary_search = f"{binary} "
      filtered = tuple(line for line in ps_stats.splitlines() if binary in line)
      if len(filtered) == 0:
        continue
      # Use the first in the group
      browser = browsers[0]
      logging.debug(f"Binary={binary}")
      logging.debug("PS status output:")
      logging.debug(filtered)
      result = self.warn(
          f"{browser.app_name} {browser.version} seems to be already running. "
          "Continue?")
      if not result:
        return False
    return True

  def _check_headless(self):
    if helper.platform.is_win:
      return True
    # We only have a $DISPLAY env var on macos if xquartz is installed
    if helper.platform.is_macos:
      return True
    if os.environ.get('DISPLAY', None) is not None:
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
    if len(self._runner.probes) == 0:
      return self.warn("No probes specified. Continue?")
    for probe in self._runner.probes:
      if not probe.pre_check(self):
        return False
    return True

  def is_ok(self):
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
  def is_success(self):
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


class Benchmark:
  pass


class Runner(abc.ABC):
  NAME = None
  DEFAULT_STORY_CLS = None

  # @property
  # @classmethod
  # def NAME(self) -> str:
  #   pass

  # @property
  # @classmethod
  # def DEFAULT_STORY_CLS(self) -> Type[stories.Story]:
  #   pass

  @staticmethod
  def get_out_dir(cwd, suffix="", test=False) -> Path:
    if test:
      return cwd / 'results' / 'test'
    if len(suffix) > 0:
      suffix = "_" + suffix
    return (cwd / 'results' /
            f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}{suffix}")

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    assert cls.__doc__ and len(cls.__doc__) > 0, \
        f"Benchmark class {cls} must provide a doc string."
    doc_title = cls.__doc__.strip().split("\n")[0]
    parser = subparsers.add_parser(
        cls.NAME,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help=doc_title,
        description=cls.__doc__.strip())
    parser.add_argument(
        "--repeat",
        default=1,
        type=int,
        help="Number of times each benchmark story is "
        "repeated. Defaults to 1")
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Results will be stored in this directory. "
        "Defaults to result/$DATE")
    parser.add_argument(
        '--throw',
        action='store_true',
        default=False,
        help="Directly throw exceptions")
    parser.add_argument("--label", type=str, help="Custom output label")
    parser.add_argument(
        '--skip-checklist',
        dest="use_checklist",
        action='store_false',
        default=True,
        help="Do not check for potential SetUp issues "
        "before running the benchmark. Enabled by default.")
    return parser

  @classmethod
  def kwargs_from_cli(cls, args):
    if args.out_dir is None:
      label = args.label or cls.NAME
      cli_dir = Path(__file__).parent.parent
      args.out_dir = cls.get_out_dir(cli_dir, label)
    return dict(
        out_dir=args.out_dir,
        browsers=args.browsers,
        repetitions=args.repeat,
        use_checklist=args.use_checklist,
        throw=args.throw)

  @classmethod
  def describe(cls):
    return {
        "name": cls.NAME,
        "description": cls.__doc__.strip(),
        "stories": [],
        "probes-default": {
            probe_cls.NAME: probe_cls.__doc__.strip()
            for probe_cls in cls.DEFAULT_STORY_CLS.PROBES
        }
    }

  def __init__(self,
               out_dir,
               browsers,
               stories,
               probes=(),
               throttle=True,
               repetitions=1,
               use_checklist=True,
               throw=False):
    assert self.NAME is not None, f"{self} has no .NAME property"
    self.out_dir = out_dir
    assert not self.out_dir.exists(), f"out_dir={self.out_dir} exists already"
    self.default_wait = 2 if throttle else 0.1
    self.browsers = browsers
    assert len(browsers) > 0, "No browsers provided"
    browser_labels = list(browser.label for browser in browsers)
    assert len(browser_labels) == len(
        set(browser_labels)), (f"Duplicated browser labels in {browser_labels}")
    self.stories = stories
    assert len(stories) > 0, "No stories provided"
    self.repetitions = repetitions
    assert self.repetitions > 0, f"Invalid repetitions={self.repetitions}"
    self.throttle = throttle
    self._use_checklist = use_checklist
    self._probes = []
    self._runs = []
    self._exceptions = ExceptionHandler(throw)
    self._attach_default_probes(probes)
    self._validate_stories()

  def _validate_stories(self):
    first_story = self.stories[0]
    first_story_class = first_story.__class__
    expected_probes_cls_list = first_story.PROBES
    for story in self.stories:
      assert isinstance(story, first_story_class), \
          f"story={story} has not the same class as {first_story}"
      assert story.PROBES == expected_probes_cls_list, \
          f"stroy={story} has different PROBES than {first_story}"
    for probe_cls in expected_probes_cls_list:
      assert inspect.isclass(probe_cls), \
          f"Story.PROBES must contain classes only, but got {type(probe_cls)}"
      self.attach_probe(probe_cls())

  def _attach_default_probes(self, probe_list):
    assert len(self._probes) == 0
    self.attach_probe(probes.RunResultsSummaryProbe())
    self.attach_probe(probes.RunDurationsProbe())
    self.attach_probe(probes.RunRunnerLogProbe())
    for probe in probe_list:
      self.attach_probe(probe)

  def attach_probe(self, probe, matching_browser_only=False):
    assert isinstance(probe, probes.Probe), \
        f"Probe must be an instance of Probe, but got {type(probe)}."
    assert probe not in self._probes, "Cannot add the same probe twice"
    self._probes.append(probe)
    for browser in self.browsers:
      if not probe.is_compatible(browser):
        if matching_browser_only:
          logging.warning(f"Skipping incompatible probe={probe.name} "
                          f"for browser={browser.short_name}")
          continue
        raise Exception(f"Probe '{probe.name}' is not compatible with browser "
                        f"{browser.type}")
      browser.attach_probe(probe)
    return probe

  @property
  def probes(self):
    return list(self._probes)

  @property
  def exceptions(self):
    return self._exceptions

  @property
  def is_success(self):
    return len(self._runs) > 0 and self._exceptions.is_success

  def sh(self, *args, shell=False, stdout=None):
    return helper.platform.sh(*args, shell=shell, stdout=stdout)

  def wait(self, seconds):
    helper.platform.sleep(seconds)

  def collect_hardware_details(self):
    self.out_dir.mkdir(parents=True, exist_ok=True)
    with (self.out_dir / 'GetHardwareDetails.details.txt').open('w') as f:
      details = helper.platform.get_hardware_details()
      f.write(details)

  def _setup(self):
    self.out_dir.mkdir(parents=True, exist_ok=True)
    if self.repetitions <= 0:
      raise Exception(f"Invalid repetitions count: {self.repetitions}")
    if len(self.browsers) == 0:
      raise Exception("No browsers provided: self.browsers is empty")
    if len(self.stories) == 0:
      raise Exception("No stories provided: self.stories is empty")
    for browser in self.browsers:
      browser.setup_binary(self)
    self._runs = list(self.get_runs())
    assert len(self._runs) > 0, "get_runs() produced no runs"
    if self._use_checklist:
      if not CheckList(self).is_ok():
        raise Exception("Thou shalt not pass the CheckList")
    self.collect_hardware_details()

  def get_runs(self):
    """Extension point for subclasses."""
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
      with helper.SystemSleepPreventer():
        self._setup()
        for run in self._runs:
          run.run(is_dry_run)
          self._exceptions.extend(run.exceptions)
        if not is_dry_run:
          self._tear_down()
        logging.info(f"RESULTS DIR: {self.out_dir}")
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
    if not helper.platform.is_thermal_throttled():
      return
    logging.info("COOLDOWN")
    for time_spent, time_left in helper.wait_with_backoff(
        helper.wait_range(1, 100)):
      if not helper.platform.is_thermal_throttled():
        break
      logging.info("COOLDOWN: still hot, waiting some more")


class SubStoryRunner(Runner):

  @classmethod
  def parse_cli_stories(cls, values):
    return tuple(story.strip() for story in values.split(","))

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers)
    parser.add_argument(
        "--stories",
        default="all",
        type=cls.parse_cli_stories,
        help="Comma-separated list of story names. Use 'all' as placeholder.")
    is_combined_group = parser.add_mutually_exclusive_group()
    is_combined_group.add_argument(
        "--combined",
        dest="separate",
        default=False,
        action='store_false',
        help="Run each story in the same session. (default)")
    is_combined_group.add_argument(
        "--separate",
        action='store_true',
        help="Run each story in a fresh browser.")
    return parser

  @classmethod
  def kwargs_from_cli(cls, args) -> dict:
    kwargs = super().kwargs_from_cli(args)
    kwargs['stories'] = cls.stories_from_cli(args)
    return kwargs

  @classmethod
  def stories_from_cli(cls, args) -> Iterable[stories.Story]:
    assert issubclass(cls.DEFAULT_STORY_CLS, stories.Story), (
        f"{cls.__name__}.DEFAULT_STORY_CLS is not a Story class. "
        f"Got '{cls.DEFAULT_STORY_CLS}' instead.")
    return cls.DEFAULT_STORY_CLS.from_names(args.stories, args.separate)

  @classmethod
  def describe(cls) -> dict:
    data = super().describe()
    data['stories'] = cls.story_names()
    return data

  @classmethod
  def story_names(cls) -> Iterable[str]:
    return cls.DEFAULT_STORY_CLS.story_names()


class PressBenchmarkStoryRunner(SubStoryRunner):

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers)
    is_live_group = parser.add_mutually_exclusive_group()
    is_live_group.add_argument(
        "--live",
        default=True,
        action='store_true',
        help="Use live/online benchmark url.")
    is_live_group.add_argument(
        "--local",
        dest="live",
        action='store_false',
        help="Use locally hosted benchmark url.")
    return parser

  @classmethod
  def stories_from_cli(cls, args) -> Iterable[stories.PressBenchmarkStory]:
    assert issubclass(cls.DEFAULT_STORY_CLS, stories.PressBenchmarkStory)
    return cls.DEFAULT_STORY_CLS.from_names(args.stories, args.separate,
                                            args.live)

  @classmethod
  def describe(cls) -> dict:
    data = super().describe()
    assert issubclass(cls.DEFAULT_STORY_CLS, stories.PressBenchmarkStory)
    data['url'] = cls.DEFAULT_STORY_CLS.URL
    data['url-local'] = cls.DEFAULT_STORY_CLS.URL_LOCAL
    return data


class RunGroup:

  def __init__(self, throw=False):
    self._exceptions = ExceptionHandler(throw)
    self._path = None
    self._merged_probe_results = None

  def _set_path(self, path: Path):
    assert self._path is None
    self._path = path
    self._merged_probe_results = probes.ProbeResultDict(path)

  @property
  def results(self) -> "probes.ProbeResultDict":
    return self._merged_probe_results

  @property
  def path(self) -> Path:
    return self._path

  @property
  def exceptions(self) -> ExceptionHandler:
    return self._exceptions

  def get_probe_results_file(self, probe: probes.Probe) -> Path:
    new_file = self.path / probe.results_file_name
    assert not new_file.exists(), \
        f"Merged file {new_file} for {self.__class__} exists already."
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

  def _merge_probe_results(self, probe: probes.Probe):
    return None


class RepetitionsRunGroup(RunGroup):
  """
  A group of Run objects that are different repetitions for the same Story with
  and the same browser.
  """

  @classmethod
  def groups(cls, runs, throw=False):
    return list(
        helper.group_by(
            runs,
            key=lambda run: (run.story, run.browser),
            group=lambda _: cls(throw)).values())

  def __init__(self, throw=False):
    super().__init__(throw)
    self._runs = []
    self._story: stories.Story = None
    self._browser: browsers.Browser = None

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
  def runs(self) -> Iterable['Run']:
    return self._runs

  @property
  def story(self) -> stories.Story:
    return self._story

  @property
  def browser(self) -> browsers.Browser:
    return self._browser

  def _merge_probe_results(self, probe: probes.Probe):
    return probe.merge_repetitions(self)  # pytype: disable=wrong-arg-types


class StoriesRunGroup(RunGroup):
  """
  A group of StoryRepetitionsRunGroups for the same browser.
  """

  def __init__(self, throw=False):
    super().__init__(throw)
    self._repetitions_groups: List[RepetitionsRunGroup] = []
    self._browser: browsers.Browser = None

  @classmethod
  def groups(cls, run_groups, throw=False):
    return list(
        helper.group_by(
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
  def runs(self) -> Iterable['Run']:
    for group in self._repetitions_groups:
      yield from group.runs

  @property
  def browser(self) -> browsers.Browser:
    return self._browser

  @property
  def stories(self) -> Iterable[stories.Story]:
    return (group.story for group in self._repetitions_groups)

  def _merge_probe_results(self, probe: probes.Probe):
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
  def runs(self) -> Iterable["Run"]:
    for group in self._story_groups:
      yield from group.runs

  def _merge_probe_results(self, probe: probes.Probe):
    return probe.merge_browsers(self)  # pytype: disable=wrong-arg-types


class Run:
  STATE_INITIAL = 0
  STATE_PREPARE = 1
  STATE_RUN = 2
  STATE_DONE = 3

  def __init__(self,
               runner: Runner,
               browser: browsers.Browser,
               story: stories.Story,
               iteration: int,
               root_dir: Path,
               name=None,
               temperature=None,
               throw=False):
    self._state = self.STATE_INITIAL
    self._run_success = None
    self._runner = runner
    self._browser = browser
    self._story = story
    self._iteration = iteration
    self._name = name
    self._out_dir = self.get_out_dir(root_dir)
    self._probe_results = probes.ProbeResultDict(self._out_dir)
    self._extra_js_flags = flags.JSFlags()
    self._extra_flags = flags.Flags()
    self._durations = helper.Durations()
    self._temperature = temperature
    self._exceptions = ExceptionHandler(throw)

  def get_out_dir(self, root_dir) -> Path:
    return root_dir / self.browser.short_name / self.story.name / str(
        self._iteration)

  @property
  def group_dir(self) -> Path:
    return self.out_dir.parent

  def actions(self, name):
    return Actions(name, self)

  @property
  def temperature(self):
    return self._temperature

  @property
  def durations(self):
    return self._durations

  @property
  def iteration(self):
    return self._iteration

  @property
  def runner(self):
    return self._runner

  @property
  def browser(self):
    return self._browser

  @property
  def story(self):
    return self._story

  @property
  def name(self):
    return self._name

  @property
  def extra_js_flags(self):
    return self._extra_js_flags

  @property
  def out_dir(self):
    return self._out_dir

  @property
  def extra_flags(self):
    return self._extra_flags

  @property
  def probes(self):
    return self._runner.probes

  @property
  def results(self):
    return self._probe_results

  @property
  def exceptions(self):
    return self._exceptions

  @property
  def is_success(self):
    return self._exceptions.is_success

  def get_browser_details_json(self) -> dict:
    details_json = self.browser.details_json()
    details_json['js_flags'] += tuple(self.extra_js_flags.get_list())
    details_json['flags'] += tuple(self.extra_flags.get_list())
    return details_json

  def get_probe_results_file(self, probe: "crossbench.probes.Probe") -> Path:
    file = self._out_dir / probe.results_file_name
    assert not file.exists(), f"Probe results file exists already. file={file}"
    return file

  def setup(self):
    logging.info('PREPARE')
    self._advance_state(self.STATE_INITIAL, self.STATE_PREPARE)
    self._run_success = None
    browser_log_file = self._out_dir / 'browser.log'
    assert not browser_log_file.exists(), \
        f"Default browser log file {browser_log_file} already exists."
    self._browser.set_log_file(browser_log_file)

    with self._durations.measure('runner-cooldown'):
      # self._runner.cool_down()
      self._runner.wait(self._runner.default_wait)

    probe_run_scopes = []
    with self._durations.measure('probes-creation'):
      probe_set = set()
      for probe in self.probes:
        assert probe not in probe_set, \
            f"Got duplicate probe name={probe.name}"
        probe_set.add(probe)
        if probe.PRODUCES_DATA:
          self._probe_results[probe] = None
        probe_run_scopes.append(probe.get_scope(self))

    with self._durations.measure('probes-setup'):
      for probe_scope in probe_run_scopes:
        probe_scope.setup(self)

    with self._durations.measure('browser-setup'):
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
    with helper.ChangeCWD(self._out_dir):
      probe_scopes = self.setup()
      self._advance_state(self.STATE_PREPARE, self.STATE_RUN)
      self._run_success = False
      logging.debug("CWD %s", self._out_dir)
      try:
        probe_start_time = datetime.now()
        probe_scope_manager = contextlib.ExitStack()
        for probe_scope in probe_scopes:
          probe_scope.set_start_time(probe_start_time)
          probe_scope_manager.enter_context(probe_scope)
        with probe_scope_manager:
          self._durations['probes-start'] = datetime.now() - \
              probe_start_time
          logging.info("RUN: BROWSER=%s STORY=%s", self._browser.short_name,
                       self.story.name)
          assert self._state == self.STATE_RUN, "Invalid state"
          with self._durations.measure('run'):
            self._story.run(self)
          self._run_success = True
      except Exception as e:
        self._exceptions.handle(e)
      finally:
        self.tear_down(probe_scopes)

  def _advance_state(self, expected, next):
    assert self._state == expected, \
        f"Invalid state got={self._state} expected={expected}"
    self._state = next

  def tear_down(self, probe_scopes, is_shutdown=False):
    self._advance_state(self.STATE_RUN, self.STATE_DONE)
    with self._durations.measure('browser-TearDown'):
      if is_shutdown:
        try:
          self._browser.quit(self._runner)
        except Exception as e:
          logging.warning(f"Error quitting browser: {e}")
          return
      try:
        self._browser.quit(self._runner)
      except Exception as e:
        logging.warning(f"Error quitting browser: {e}")
        self._exceptions.handle(e)
    with self._durations.measure('probes-TearDown'):
      logging.info("TEARDOWN")
      self._tear_down_probe_scopes(probe_scopes)

  def _tear_down_probe_scopes(self, probe_scopes):
    for probe_scope in reversed(probe_scopes):
      try:
        assert probe_scope.run == self
        probe_results = probe_scope.tear_down(self)
        probe = probe_scope.probe
        if probe_results is None:
          logging.warning(
              f"Probe did not extract any data. probe={probe} run={self}")
        self._probe_results[probe] = probe_results
      except Exception as e:
        self._exceptions.handle(e)


class Actions(helper.TimeScope):
  _run: Run
  _browser: browsers.Browser
  _runner: Runner
  _parent: Actions
  _is_active: bool = False

  def __init__(self, message, run: Run, runner=None, browser=None, parent=None):
    assert len(message) > 0, "Actions need a name"
    super().__init__(message)
    self._run = run
    self._browser = browser or (run and run.browser)
    self._runner = runner or run.runner
    self._parent = parent

  @property
  def run(self):
    return self._run

  def __enter__(self):
    super().__enter__()
    self._is_active = True
    logging.info(f"ACTION START {self._message}")
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    self._is_active = False
    logging.info(f"ACTION END {self._message}")
    super().__exit__(exc_type, exc_value, exc_traceback)

  def _assert_is_active(self):
    assert self._is_active, "Actions have to be used in a with scope"

  def js(self, js_code: str, timeout=10, arguments=(), **kwargs):
    self._assert_is_active()
    assert len(js_code) > 0, "js_code must be a valid JS script"
    if kwargs:
      js_code = js_code.format(**kwargs)
    return self._browser.js(self._runner, js_code, timeout, arguments=arguments)

  def wait_js_condition(self, js_code: str, wait_range):
    assert "return" in js_code, (
        f"Missing return statement in js-wait code: {js_code}")
    for time_spent, time_left in helper.wait_with_backoff(wait_range):
      result = self.js(js_code, timeout=time_left)
      if result:
        return time_spent
      assert result is False, \
          f"js_code did not return a bool, but got: {result}"

  def navigate_to(self, url: str):
    self._assert_is_active()
    self._browser.show_url(self._runner, url)

  def wait(self, seconds=1):
    self._assert_is_active()
    helper.platform.sleep(seconds)
