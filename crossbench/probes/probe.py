# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import logging
from datetime import datetime
from pathlib import Path
from typing import Set

from crossbench import browsers, helper, runner


class Probe(abc.ABC):
  """
  Abstract Probe class.

  Probes are responsible for extracting performance numbers from websites
  / stories.

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
  def NAME(self):
    pass

  # Set to False if the Probe cannot be used with arbitrary Stories or Pages
  IS_GENERAL_PURPOSE = True
  PRODUCES_DATA = True
  # Set to True if the probe only works on battery power
  BATTERY_ONLY = False

  _browsers: Set[browsers.Browser]

  @classmethod
  def get_subclasses(cls):
    for subclass in helper.get_subclasses(cls):
      if len(subclass.__abstractmethods__) > 0:
        continue
      if subclass.__name__.startswith("_"):
        continue
      assert isinstance(subclass.NAME, str)
      yield subclass

  @classmethod
  def get_names(cls):
    return (subclass.NAME for subclass in cls.get_subclasses())

  def __init__(self):
    assert self.name is not None, "A Probe must define a name"
    self._browsers = set()

  @property
  def name(self):
    return self.NAME

  @property
  def results_file_name(self):
    return self.name

  def is_compatible(self, browser):
    """
    Returns a boolean to indicate whether this Probe can be used with the given
    Browser. Override to make browser-specific Probes.
    """
    return True

  @property
  def is_attached(self):
    return len(self._browsers) > 0

  def attach(self, browser):
    assert self.is_compatible(browser), \
        f"Probe {self.name} is not compatible with browser {browser.type}"
    assert browser not in self._browsers, \
        f"Probe={self.name} is attached multiple times to the same browser"
    self._browsers.add(browser)

  def pre_check(self, checklist) -> bool:
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

  def merge_repetitions(self, group: runner.RepetitionsRunGroup):
    """
    Can be used to merge probe data from multiple repetitions of the same story.
    Return None, a result file Path (or a list of Paths)
    """
    return None

  def merge_stories(self, group: runner.StoriesRunGroup):
    """
    Can be used to merge probe data from multiple stories for the same browser.
    Return None, a result file Path (or a list of Paths)
    """
    return None

  def merge_browsers(self, group: runner.BrowsersRunGroup):
    """
    Can be used to merge all probe data (from multiple stories and browsers.)
    Return None, a result file Path (or a list of Paths)
    """
    return None

  def get_scope(self, run):
    assert self.is_attached, (
        f"Probe {self.name} is not properly attached to a browser")
    return self.Scope(self, run)

  class Scope(abc.ABC):
    """
    A scope during which a probe is actively collecting data.
    Override in Probe subclasses to implement actual performance data
    collection.
    - The data should be written to self.results_file.
    - A file / list / dict of result file Paths should be returned by the
      override tear_down() method
    """

    def __init__(self, probe, run):
      self._probe = probe
      self._run = run
      self._default_results_file = run.get_probe_results_file(probe)
      self._is_active = False
      self._is_success = False
      self._start_time = None
      self._stop_time = None

    def set_start_time(self, start_datetime):
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
        self._stop_time = datetime.now()

    @property
    def probe(self):
      return self._probe

    @property
    def run(self):
      return self._run

    @property
    def start_time(self):
      """
      Returns a unified start time that is the same for all Probe.Scopes
      within a run. This can be to account for startup delays caused by other
      Probes.
      """
      return self._start_time

    @property
    def duration(self):
      return self._stop_time - self._start_time

    @property
    def is_success(self):
      return self._is_success

    @property
    def results_file(self):
      return self._default_results_file

    def setup(self, run):
      """
      Called before starting the browser, typically used to set run-specific
      browser flags.
      """
      pass

    @abc.abstractmethod
    def start(self, run):
      """
      Called immediately before starting the given Run.
      This method should have as little overhead as possible. If possible,
      delegate heavy computation to the "SetUp" method.
      """
      pass

    @abc.abstractmethod
    def stop(self, run):
      """
      Called immediately after finishing the given Run.
      This method should have as little overhead as possible. If possible,
      delegate heavy computation to the "collect" method.
      """
      return None

    @abc.abstractmethod
    def tear_down(self, run):
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


class ProbeResultDict:
  """
  Maps Probes to their result files Paths.
  """

  def __init__(self, path: Path):
    self._path = path
    self._dict = {}

  def __setitem__(self, probe: Probe, results):
    if results is None:
      self._dict[probe.name] = None
      return
    self._check_result_type(probe, results)
    self._dict[probe.name] = results

  def _check_result_type(self, probe: Probe, results):
    assert isinstance(results, (Path, str, tuple, dict)), (
        f"Probe name={probe.name} should produce Path, URL or tuples/dicts "
        f"thereof, but got: {results}")
    check_items = None
    if isinstance(results, tuple):
      check_items = results
    elif isinstance(results, dict):
      check_items = results.values()
    if check_items:
      for result in check_items:
        assert isinstance(result, (Path, str)), (
            f"Expected probe={probe.name} tuple results to contain Paths or "
            f"strings, but got: {result}")

  def __getitem__(self, probe: Probe):
    return self._dict[probe.name]

  def __contains__(self, probe: Probe):
    return probe.name in self._dict

  def to_json(self):
    data = {}
    for probe_name, results in self._dict.items():
      if isinstance(results, (Path, str)):
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
