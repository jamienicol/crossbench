# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import inspect
import json
import logging
import pathlib
import sys
import traceback
from dataclasses import dataclass
from types import TracebackType
from typing import (TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence,
                    Tuple, Type)

if TYPE_CHECKING:
  import crossbench.runner

import crossbench as cb
import crossbench.benchmarks
import crossbench.browsers
import crossbench.env
import crossbench.flags
import crossbench.probes
import crossbench.probes.runner
import crossbench.stories
from crossbench import helper

TInfoStack = Tuple[str, ...]

TExceptionTypes = Tuple[Type[BaseException], ...]


class ExceptionHandler:

  @dataclass
  class Entry:
    traceback: str
    exception: BaseException
    info_stack: TInfoStack

  class _ContextManager:

    def __init__(self, exception_handler: ExceptionHandler,
                 exception_types: TExceptionTypes, entries: Tuple[str]):
      self._handler = exception_handler
      self._exception_types = exception_types
      self._added_info_stack_entries = entries
      self._previous_info_stack: TInfoStack = ()

    def __enter__(self):
      self._handler._pending_exceptions.clear()
      self._previous_info_stack = self._handler.info_stack
      self._handler._info_stack = self._previous_info_stack + (
          self._added_info_stack_entries)

    def __exit__(self, exception_type: Optional[Type[BaseException]],
                 exception_value: Optional[BaseException],
                 traceback: Optional[TracebackType]) -> bool:
      if not exception_value:
        self._handler._info_stack = self._previous_info_stack
        return False
      if self._exception_types and issubclass(exception_type,
                                              self._exception_types):
        # Handle matching exceptions directly here and prevent further
        # exception handlers by returning True.
        self._handler.handle(exception_value)
        self._handler._info_stack = self._previous_info_stack
        return True
      if exception_value not in self._handler._pending_exceptions:
        self._handler._pending_exceptions[
            exception_value] = self._handler.info_stack

  def __init__(self, throw: bool = False):
    self._exceptions: List[ExceptionHandler.Entry] = []
    self.throw: bool = throw
    # The info_stack adds additional meta information to handle exceptions.
    # Unlike the source-based backtrace, this can contain dynamic information
    # for easier debugging.
    self._info_stack: TInfoStack = ()
    # Associates raised exception with the info_stack at that time for later
    # use in the `handle` method.
    # This is cleared whenever we enter a  new _ContextManager.
    self._pending_exceptions: Dict[BaseException, TInfoStack] = {}

  @property
  def is_success(self) -> bool:
    return len(self._exceptions) == 0

  @property
  def info_stack(self) -> TInfoStack:
    return self._info_stack

  @property
  def exceptions(self) -> List[ExceptionHandler.Entry]:
    return self._exceptions

  def info(self, *stack_entries: str) -> _ContextManager:
    return self._ContextManager(self, tuple(), stack_entries)

  def handler(self,
              *stack_entries: str,
              exceptions: TExceptionTypes = (Exception,)) -> _ContextManager:
    return self._ContextManager(self, exceptions, stack_entries)

  def extend(self, handler: ExceptionHandler, is_nested: bool = False):
    if is_nested:
      self._extend_with_prepended_stack_info(handler)
    else:
      self._exceptions.extend(handler.exceptions)

  def _extend_with_prepended_stack_info(self, handler: ExceptionHandler):
    for entry in handler.exceptions:
      merged_info_stack = self.info_stack + entry.info_stack
      merged_entry = self.Entry(entry.traceback, entry.exception,
                                merged_info_stack)
      self._exceptions.append(merged_entry)

  def handle(self, e: BaseException):
    if isinstance(e, KeyboardInterrupt):
      # Fast exit on KeyboardInterrupts for a better user experience.
      sys.exit(0)
    tb: str = traceback.format_exc()
    stack = self.info_stack
    if e in self._pending_exceptions:
      stack = self._pending_exceptions[e]
    self._exceptions.append(self.Entry(tb, e, stack))
    logging.info("Intermediate Exception: %s", e)
    logging.debug(tb)
    if self.throw:
      raise

  def log(self):
    if self.is_success:
      return
    logging.error("ERRORS occurred:")
    for entry in self._exceptions:
      logging.debug("-" * 80)
      logging.debug(entry.exception)
      logging.debug(entry.traceback)
    for info_stack, entries in helper.group_by(
        self._exceptions, key=lambda entry: tuple(entry.info_stack)).items():
      logging.error("=" * 80)
      if info_stack:
        info = "Info: "
        joiner = "\n" + (" " * (len(info) - 2)) + "> "
        logging.error(f"{info}{joiner.join(info_stack)}")
      for entry in entries:
        logging.error("- " * 40)
        logging.error(f"Type: {entry.exception.__class__.__name__}:")
        logging.error(f"      {entry.exception}")

  def to_json(self) -> list:
    return [{
        "title": str(entry.exception),
        "trace": str(entry.traceback),
        "info_stack": entry.info_stack
    } for entry in self._exceptions]


class Runner:

  @classmethod
  def get_out_dir(cls, cwd: pathlib.Path, suffix="",
                  test=False) -> pathlib.Path:
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

    return parser

  @classmethod
  def kwargs_from_cli(cls, args):
    if args.out_dir is None:
      label = args.label or args.benchmark_cls.NAME
      cli_dir = pathlib.Path(__file__).parent.parent
      args.out_dir = cls.get_out_dir(cli_dir, label)
    return {
        "out_dir": args.out_dir,
        "browsers": args.browsers,
        "repetitions": args.repeat,
        "throw": args.throw,
    }

  def __init__(
      self,
      out_dir: pathlib.Path,
      browsers: Sequence[cb.browsers.Browser],
      benchmark: cb.benchmarks.Benchmark,
      additional_probes: Iterable[cb.probes.Probe] = (),
      platform: helper.Platform = helper.platform,
      env_config: Optional[cb.env.HostEnvironmentConfig] = None,
      env_validation_mode: cb.env.ValidationMode = cb.env.ValidationMode.THROW,
      throttle: bool = True,
      repetitions: int = 1,
      throw: bool = False):
    self.out_dir = out_dir
    assert not self.out_dir.exists(), f"out_dir={self.out_dir} exists already"
    self.out_dir.mkdir(parents=True)
    self.default_wait: float = 2 if throttle else 0.1
    self.browsers = browsers
    self._validate_browsers()
    self._browser_platform = browsers[0].platform
    self._benchmark = benchmark
    self.stories = benchmark.stories
    self.repetitions = repetitions
    assert self.repetitions > 0, f"Invalid repetitions={self.repetitions}"
    self.throttle = throttle
    self._probes: List[cb.probes.Probe] = []
    self._runs: List[Run] = []
    self._exceptions = ExceptionHandler(throw)
    self._platform = platform
    self._env = cb.env.HostEnvironment(
        self,  # pytype: disable=wrong-arg-types
        env_config,
        env_validation_mode)
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
    self.attach_probe(cb.probes.runner.RunResultsSummaryProbe())
    self.attach_probe(cb.probes.runner.RunDurationsProbe())
    self.attach_probe(cb.probes.runner.RunRunnerLogProbe())
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
  def platform(self) -> helper.Platform:
    return self._platform

  @property
  def browser_platform(self) -> helper.Platform:
    return self._browser_platform

  def sh(self, *args, shell=False, stdout=None):
    return self._platform.sh(*args, shell=shell, stdout=stdout)

  def wait(self, seconds):
    self._platform.sleep(seconds)

  def collect_system_details(self):
    with (self.out_dir / "system_details.json").open("w") as f:
      details = self._platform.system_details()
      json.dump(details, f, indent=2)

  def _setup(self):
    assert self.repetitions > 0, f"Invalid repetitions count: {self.repetitions}"
    assert self.browsers, "No browsers provided: self.browsers is empty"
    assert self.stories, "No stories provided: self.stories is empty"
    for browser in self.browsers:
      browser.setup_binary(self)  # pytype: disable=wrong-arg-types
    self._runs = list(self.get_runs())
    assert self._runs, f"{type(self)}.get_runs() produced no runs"
    self._env.setup()
    self._benchmark.setup()
    self.collect_system_details()

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
              name=f"{story.name}[{iteration}]",
              throw=self._exceptions.throw)

  def run(self, is_dry_run=False):
    try:
      with helper.SystemSleepPreventer():
        self._run(is_dry_run)
    except KeyboardInterrupt:
      # Fast exit in case without a stacktrace for better usability
      return

  def _run(self, is_dry_run=False):
    self._setup()
    failed: List[Run] = []
    for run in self._runs:
      run.run(is_dry_run)
      if not run.exceptions.is_success:
        self._exceptions.extend(run.exceptions)
        failed.append(run)
    if not is_dry_run:
      self._tear_down()
    logging.info("RESULTS DIR: %s", self.out_dir)
    if not self.is_success:
      self._exceptions.log()
      raise Exception(
          f"Runs Failed: {len(failed)}/{len(self._runs)} runs failed.")

  def _tear_down(self):
    logging.info("MERGING PROBE DATA: iterations")
    throw = self._exceptions.throw
    repetitions_groups = RepetitionsRunGroup.groups(self._runs, throw)
    with self._exceptions.info("Merging results from multiple repetitions"):
      for repetitions_group in repetitions_groups:
        repetitions_group.merge(self)
        self._exceptions.extend(repetitions_group.exceptions, is_nested=True)

    logging.info("MERGING PROBE DATA: stories")
    story_groups = StoriesRunGroup.groups(repetitions_groups, throw)
    with self._exceptions.info("Merging results from multiple stories"):
      for story_group in story_groups:
        story_group.merge(self)
        self._exceptions.extend(story_group.exceptions, is_nested=True)

    logging.info("MERGING PROBE DATA: browsers")
    browser_group = BrowsersRunGroup(story_groups, throw)
    with self._exceptions.info("Merging results from multiple browsers"):
      browser_group.merge(self)
      self._exceptions.extend(browser_group.exceptions, is_nested=True)

  def cool_down(self, default_wait=None):
    # Cool down between runs
    default_wait = default_wait or self.default_wait
    self.wait(default_wait)
    if not self._platform.is_thermal_throttled():
      return
    logging.info("COOLDOWN")
    for time_spent, time_left in helper.wait_with_backoff(
        helper.wait_range(1, 100)):
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

  @property
  def info_stack(self) -> TInfoStack:
    return ()

  def get_probe_results_file(self, probe: cb.probes.Probe) -> pathlib.Path:
    new_file = self.path / probe.results_file_name
    assert not new_file.exists(), (
        f"Merged file {new_file} for {self.__class__} exists already.")
    return new_file

  def merge(self, runner: Runner):
    with self._exceptions.info(*self.info_stack):
      for probe in reversed(runner.probes):
        with self._exceptions.handler(f"Probe {probe.name} merge results"):
          results = self._merge_probe_results(probe)
          if results is None:
            continue
          self._merged_probe_results[probe] = results

  def _merge_probe_results(self, probe: cb.probes.Probe):
    return None


class RepetitionsRunGroup(RunGroup):
  """
  A group of Run objects that are different repetitions for the same Story with
  and the same browser.
  """

  @classmethod
  def groups(cls, runs: Iterable[Run],
             throw=False) -> List[RepetitionsRunGroup]:
    return list(
        helper.group_by(
            runs,
            key=lambda run: (run.story, run.browser),
            group=lambda _: cls(throw)).values())

  def __init__(self, throw=False):
    super().__init__(throw)
    self._runs: List[Run] = []
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

  @property
  def info_stack(self) -> TInfoStack:
    return (f"browser={self.browser.label}", f"story={self.story}")

  def _merge_probe_results(self, probe: cb.probes.Probe
                          ) -> Optional[cb.probes.ProbeResultType]:
    return probe.merge_repetitions(self)


class StoriesRunGroup(RunGroup):
  """
  A group of StoryRepetitionsRunGroups for the same browser.
  """

  def __init__(self, throw=False):
    super().__init__(throw)
    self._repetitions_groups: List[RepetitionsRunGroup] = []
    self._browser: cb.browsers.Browser = None

  @classmethod
  def groups(cls, run_groups: Iterable[RepetitionsRunGroup],
             throw=False) -> List[StoriesRunGroup]:
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
  def runs(self) -> Iterable[Run]:
    for group in self._repetitions_groups:
      yield from group.runs

  @property
  def browser(self) -> cb.browsers.Browser:
    return self._browser

  @property
  def info_stack(self) -> TInfoStack:
    return (f"browser={self.browser.label}",)

  @property
  def stories(self) -> Iterable[cb.stories.Story]:
    return (group.story for group in self._repetitions_groups)

  def _merge_probe_results(self, probe: cb.probes.Probe
                          ) -> Optional[cb.probes.ProbeResultType]:
    return probe.merge_stories(self)


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

  def _merge_probe_results(self, probe: cb.probes.Probe
                          ) -> Optional[cb.probes.ProbeResultType]:
    return probe.merge_browsers(self)


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
    assert iteration >= 0
    self._iteration = iteration
    self._name = name
    self._out_dir = self.get_out_dir(root_dir).absolute()
    self._probe_results = cb.probes.ProbeResultDict(self._out_dir)
    self._extra_js_flags = cb.flags.JSFlags()
    self._extra_flags = cb.flags.Flags()
    self._durations = helper.Durations()
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
  def info_stack(self) -> TInfoStack:
    return (
        f"Run({self.name})",
        f"browser={self.browser.label} binary={self.browser.path}",
        f"story={self.story}",
        f"iteration={self.iteration}",
    )

  @property
  def temperature(self):
    return self._temperature

  @property
  def durations(self) -> helper.Durations:
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
  def platform(self) -> helper.Platform:
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

  @contextlib.contextmanager
  def measure(self, label):
    # Return a combined context manager that adds an named exception info
    # and measures the time during the with-scope.
    with self._exceptions.info(label) as stack, self._durations.measure(
        label) as timer:
      yield (stack, timer)

  def exception_info(self, *stack_entries: str):
    return self._exceptions.info(*stack_entries)

  def exception_handler(self, *stack_entries: str, exceptions=(Exception,)):
    return self._exceptions.handler(*stack_entries, exceptions=exceptions)

  def get_browser_details_json(self) -> dict:
    details_json = self.browser.details_json()
    details_json["js_flags"] += tuple(self.extra_js_flags.get_list())
    details_json["flags"] += tuple(self.extra_flags.get_list())
    return details_json

  def get_probe_results_file(self, probe: cb.probes.Probe) -> pathlib.Path:
    file = self._out_dir / probe.results_file_name
    assert not file.exists(), f"Probe results file exists already. file={file}"
    return file

  def setup(self) -> List[cb.probes.Probe.Scope]:
    logging.info("PREPARE")
    self._advance_state(self.STATE_INITIAL, self.STATE_PREPARE)
    self._run_success = None
    browser_log_file = self._out_dir / "browser.log"
    assert not browser_log_file.exists(), (
        f"Default browser log file {browser_log_file} already exists.")
    self._browser.set_log_file(browser_log_file)

    with self.measure("runner-cooldown"):
      # self._runner.cool_down()
      self._runner.wait(self._runner.default_wait)

    probe_run_scopes: List[cb.probes.Probe.Scope] = []
    with self.measure("probes-creation"):
      probe_set = set()
      for probe in self.probes:
        assert probe not in probe_set, (
            f"Got duplicate probe name={probe.name}")
        probe_set.add(probe)
        if probe.PRODUCES_DATA:
          self._probe_results[probe] = None
        probe_run_scopes.append(probe.get_scope(self))

    with self.measure("probes-setup"):
      for probe_scope in probe_run_scopes:
        with self.exception_info(f"Probe {probe_scope.name} setup"):
          probe_scope.setup(self)

    with self.measure("browser-setup"):
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

    with helper.ChangeCWD(self._out_dir), self.exception_info(*self.info_stack):
      probe_scopes = self.setup()
      self._advance_state(self.STATE_PREPARE, self.STATE_RUN)
      self._run_success = False
      logging.debug("CWD %s", self._out_dir)
      try:
        self._run(probe_scopes)
      except Exception as e:
        self._exceptions.handle(e)
      finally:
        self.tear_down(probe_scopes)

  def _run(self, probe_scopes: Sequence[cb.probes.Probe.Scope]):
    probe_start_time = dt.datetime.now()
    probe_scope_manager = contextlib.ExitStack()

    for probe_scope in probe_scopes:
      probe_scope.set_start_time(probe_start_time)
      probe_scope_manager.enter_context(probe_scope)

    with probe_scope_manager:
      self._durations["probes-start"] = (dt.datetime.now() - probe_start_time)
      logging.info("RUN: BROWSER=%s STORY=%s", self._browser.short_name,
                   self.story.name)
      assert self._state == self.STATE_RUN, "Invalid state"
      try:
        with self.measure("run"):
          self._story.run(self)
        self._run_success = True
      except TimeoutError as e:
        # Handle TimeoutError earlier since they might be caused by
        # throttled down non-foreground browser.
        self._exceptions.handle(e)
      self._check_browser_foreground()

  def _check_browser_foreground(self):
    if not self.browser.pid:
      return
    info = self.platform.foreground_process()
    if not info:
      return
    assert info["pid"] == self.browser.pid, (
        f"Browser(name={self.browser.short_name} pid={self.browser.pid})) "
        "was not in the foreground at the end of the benchmark. "
        "Background apps and tabs can be heavily throttled.")

  def _advance_state(self, expected, next):
    assert self._state == expected, (
        f"Invalid state got={self._state} expected={expected}")
    self._state = next

  def tear_down(self,
                probe_scopes: List[cb.probes.Probe.Scope],
                is_shutdown=False):
    self._advance_state(self.STATE_RUN, self.STATE_DONE)
    with self.measure("browser-tear_down"):
      if is_shutdown:
        try:
          self._browser.quit(self._runner)  # pytype: disable=wrong-arg-types
        except Exception as e:
          logging.warning("Error quitting browser: %s", e)
          return
      with self._exceptions.handler("Quit browser"):
        self._browser.quit(self._runner)  # pytype: disable=wrong-arg-types
    with self.measure("probes-tear_down"):
      logging.info("TEARDOWN")
      self._tear_down_probe_scopes(probe_scopes)

  def _tear_down_probe_scopes(self, probe_scopes: List[cb.probes.Probe.Scope]):
    for probe_scope in reversed(probe_scopes):
      with self.exceptions.handler(f"Probe {probe_scope.name} teardown"):
        assert probe_scope.run == self
        probe_results: Optional[
            cb.probes.ProbeResultType] = probe_scope.tear_down(self)
        probe = probe_scope.probe
        if probe_results is None:
          logging.warning("Probe did not extract any data. probe=%s run=%s",
                          probe, self)
        self._probe_results[probe] = probe_results


class Actions(helper.TimeScope):

  def __init__(self,
               message: str,
               run: Run,
               runner: Optional[cb.runner.Runner] = None,
               browser: Optional[cb.browsers.Browser] = None):
    assert message, "Actions need a name"
    super().__init__(message)
    self._stack = run.exceptions.info(f"Action: {message}")
    self._run = run
    self._browser = browser or run.browser
    self._runner = runner or run.runner
    self._is_active: bool = False

  @property
  def run(self) -> Run:
    return self._run

  @property
  def platform(self) -> helper.Platform:
    return self._run.platform

  def __enter__(self):
    self._stack.__enter__()
    super().__enter__()
    self._is_active = True
    logging.info("ACTION START %s", self._message)
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    self._is_active = False
    self._stack.__exit__(exc_type, exc_value, exc_traceback)
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

  def wait_js_condition(self, js_code: str, wait_range: helper.wait_range):
    assert "return" in js_code, (
        f"Missing return statement in js-wait code: {js_code}")
    for time_spent, time_left in helper.wait_with_backoff(wait_range):
      result = self.js(js_code, timeout=time_left)
      if result:
        return time_spent
      assert result is False, (
          f"js_code did not return a bool, but got: {result}\n"
          f"js-code: {js_code}")

  def navigate_to(self, url: str):
    self._assert_is_active()
    self._browser.show_url(self._runner, url)

  def wait(self, seconds: float = 1):
    self._assert_is_active()
    self.platform.sleep(seconds)
