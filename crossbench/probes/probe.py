# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import datetime as dt
import logging
import pathlib
from typing import Any, Iterable, Optional, Set, Dict, Tuple, TypeVar, Generic, Union, TYPE_CHECKING

if TYPE_CHECKING:
  import crossbench as cb

import crossbench.helper as helper

ProbeT = TypeVar('ProbeT', bound="cb.probes.Probe")


class Probe(abc.ABC):
  """
  Abstract Probe class.

  Probes are responsible for extracting performance numbers from websites
  / cb.stories

  Probe interface:
  - scope(): Return a custom Probe.Scope (see below)
  - is_compatible(): Use for checking whether a Probe can be used with a
    given browser
  - pre_check(): Customize to display warnings before using Probes with
    incompatible settings.
  The Probe object can the customize how to merge probe (performance) date at
  multiple levels:
  - multiple repetitions of the same story
  - merged repetitions from multiple stories (same browser)
  - Probe data from all Runs

  Probes use a Probe.Scope that is active during a story-Run.
  The Probe.Scope class defines a customizable interface
  - setup(): Used for high-overhead Probe initialization
  - start(): Low-overhead start-to-measure signal
  - stop():  Low-overhead stop-to-measure signal
  - tear_down(): Used for high-overhead Probe cleanup

  """

  @property
  @abc.abstractmethod
  def NAME(self) -> str:
    pass

  @classmethod
  def from_config(cls, config_data: Dict) -> Probe:
    kwargs = cls.kwargs_from_config(config_data)
    if config_data:
      raise ValueError(
          f"Config contains unused properties: {', '.join(config_data.keys())}")
    return cls(**kwargs)

  # Set to False if the Probe cannot be used with arbitrary Stories or Pages
  IS_GENERAL_PURPOSE: bool = True
  PRODUCES_DATA: bool = True
  # Set to True if the probe only works on battery power
  BATTERY_ONLY: bool = False

  _browsers: Set[cb.browsers.Browser]
  _browser_platform: cb.helper.Platform

  def __init__(self):
    assert self.name is not None, "A Probe must define a name"
    self._browsers = set()

  @property
  def browser_platform(self) -> cb.helper.Platform:
    return self._browser_platform

  @property
  def runner_platform(self) -> cb.helper.Platform:
    # TODO(cbruni): support remote platforms
    return helper.platform

  @property
  def name(self) -> str:
    return self.NAME

  @property
  def results_file_name(self) -> str:
    return self.name

  def is_compatible(self, browser: cb.browsers.Browser) -> bool:
    """
    Returns a boolean to indicate whether this Probe can be used with the given
    Browser. Override to make browser-specific Probes.
    """
    return True

  @property
  def is_attached(self) -> bool:
    return len(self._browsers) > 0

  def attach(self, browser: cb.browsers.Browser):
    assert self.is_compatible(browser), (
        f"Probe {self.name} is not compatible with browser {browser.type}")
    assert browser not in self._browsers, (
        f"Probe={self.name} is attached multiple times to the same browser")
    if not self._browsers:
      self._browser_platform = browser.platform
    else:
      assert self._browser_platform == browser.platform, (
          "All browsers must run on the same platform"
          f"existing={self._browser_platform }, new={browser.platform}")
    self._browsers.add(browser)

  def pre_check(self, checklist: cb.runner.CheckList) -> bool:
    """
    Part of the Checklist, make sure everything is set up correctly for a probe
    to run.
    """
    # Ensure that the proper super methods for setting up a probe were
    # called.
    assert self.is_attached, (
        f"Probe {self.name} is not properly attached to a browser")
    for browser in self._browsers:
      assert self.is_compatible(browser)
    return True

  def merge_repetitions(self, group: cb.runner.RepetitionsRunGroup
                       ) -> Optional[ProbeResultType]:
    """
    Can be used to merge probe data from multiple repetitions of the same story.
    Return None, a result file Path (or a list of Paths)
    """
    return None

  def merge_stories(self, group: cb.runner.StoriesRunGroup
                   ) -> Optional[ProbeResultType]:
    """
    Can be used to merge probe data from multiple stories for the same browser.
    Return None, a result file Path (or a list of Paths)
    """
    return None

  def merge_browsers(self, group: cb.runner.BrowsersRunGroup
                    ) -> Optional[ProbeResultType]:
    """
    Can be used to merge all probe data (from multiple stories and browsers.)
    Return None, a result file Path (or a list of Paths)
    """
    return None

  def get_scope(self: ProbeT, run) -> cb.probes.Probe.Scope[ProbeT]:
    assert self.is_attached, (
        f"Probe {self.name} is not properly attached to a browser")
    return self.Scope(self, run)

  class Scope(Generic[ProbeT], metaclass=abc.ABCMeta):
    """
    A scope during which a probe is actively collecting data.
    Override in Probe subclasses to implement actual performance data
    collection.
    - The data should be written to self.results_file.
    - A file / list / dict of result file Paths should be returned by the
      override tear_down() method
    """

    def __init__(self, probe: ProbeT, run: cb.runner.Run):
      self._probe = probe
      self._run = run
      self._default_results_file = run.get_probe_results_file(probe)
      self._is_active = False
      self._is_success = False
      self._start_time: Optional[dt.datetime] = None
      self._stop_time: Optional[dt.datetime] = None

    def set_start_time(self, start_datetime: dt.datetime):
      assert self._start_time is None
      self._start_time = start_datetime

    def __enter__(self):
      assert not self._is_active
      assert not self._is_success
      try:
        self._is_active = True
        self.start(self._run)
      except Exception as e:
        self._run.exceptions.handle(e)
      return self

    def __exit__(self, exc_type, exc_value, traceback):
      assert self._is_active
      try:
        self.stop(self._run)
        self._is_success = True
        assert self._stop_time is None
      except Exception as e:
        self._run.exceptions.handle(e)
      finally:
        self._stop_time = dt.datetime.now()

    @property
    def probe(self) -> ProbeT:
      return self._probe

    @property
    def run(self) -> cb.runner.Run:
      return self._run

    @property
    def browser(self) -> cb.browsers.Browser:
      return self._run.browser

    @property
    def runner(self) -> cb.runner.Runner:
      return self._run.runner

    @property
    def browser_platform(self) -> cb.helper.Platform:
      return self.browser.platform

    @property
    def runner_platform(self) -> cb.helper.Platform:
      return self.runner.platform

    @property
    def start_time(self) -> dt.datetime:
      """
      Returns a unified start time that is the same for all Probe.Scopes
      within a run. This can be to account for startup delays caused by other
      Probes.
      """
      assert self._start_time
      return self._start_time

    @property
    def duration(self) -> dt.timedelta:
      assert self._start_time and self._stop_time
      return self._stop_time - self._start_time

    @property
    def is_success(self) -> bool:
      return self._is_success

    @property
    def results_file(self) -> pathlib.Path:
      return self._default_results_file

    def setup(self, run):
      """
      Called before starting the browser, typically used to set run-specific
      browser flags.
      """
      pass

    @abc.abstractmethod
    def start(self, run: cb.runner.Run):
      """
      Called immediately before starting the given Run.
      This method should have as little overhead as possible. If possible,
      delegate heavy computation to the "SetUp" method.
      """
      pass

    @abc.abstractmethod
    def stop(self, run: cb.runner.Run):
      """
      Called immediately after finishing the given Run.
      This method should have as little overhead as possible. If possible,
      delegate heavy computation to the "collect" method.
      """
      return None

    @abc.abstractmethod
    def tear_down(self, run: cb.runner.Run) -> Optional[ProbeResultType]:
      """
      Called after stopping all probes and shutting down the browser.
      Returns
      - None if no data was collected
      - If Data was collected:
        - Either a path (or list of paths) to results file
        - Directly a primitive json-serializable object containing the data
      """
      return None


# ------------------------------------------------------------------------------

BasicProbeResultType = Union[pathlib.Path, str]
ProbeResultType = Union[None, BasicProbeResultType, Tuple[BasicProbeResultType],
                        Dict[str, BasicProbeResultType]]


class ProbeResultDict:
  """
  Maps Probes to their result files Paths.
  """

  def __init__(self, path: pathlib.Path):
    self._path = path
    self._dict: Dict[str, ProbeResultType] = {}

  def __setitem__(self, probe: Probe, results: ProbeResultType):
    if results is None:
      self._dict[probe.name] = None
      return
    self._check_result_type(probe, results)
    self._dict[probe.name] = results

  def _check_result_type(self, probe: Probe, results: ProbeResultType):
    assert isinstance(results, (pathlib.Path, str, tuple, dict)), (
        f"Probe name={probe.name} should produce Path, URL or tuples/dicts "
        f"thereof, but got: {results}")
    check_items: Iterable[Union[pathlib.Path, str]] = ()
    if isinstance(results, tuple):
      check_items = results
    elif isinstance(results, dict):
      check_items = results.values()
    else:
      return
    for result in check_items:
      assert isinstance(result, (pathlib.Path, str)), (
          f"Expected probe={probe.name} tuple results to contain Paths or "
          f"strings, but got: {result}")

  def __getitem__(self, probe: Probe) -> ProbeResultType:
    return self._dict[probe.name]

  def __contains__(self, probe: Probe) -> bool:
    return probe.name in self._dict

  def to_json(self):
    data: Dict[str, Any] = {}
    for probe_name, results in self._dict.items():
      if isinstance(results, (pathlib.Path, str)):
        data[probe_name] = str(results)
      else:
        if results is None:
          logging.debug("probe=%s did not produce any data.", probe_name)
          data[probe_name] = None
        elif isinstance(results, dict):
          data[probe_name] = {key: str(value) for key, value in results.items()}
        elif isinstance(results, tuple):
          data[probe_name] = tuple(str(path) for path in results)
    return data
