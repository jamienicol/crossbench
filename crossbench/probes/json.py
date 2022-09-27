# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import json
import logging
import math
import pathlib
from re import A
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  import crossbench as cb
import crossbench.probes as probes


class JsonResultProbe(probes.Probe, metaclass=abc.ABCMeta):
  """
  Abstract Probe that stores a JSON result extracted by the `to_json` method

  Tje `to_json` is provided by subclasses. A typical examples includes just
  running a JS script on the page.
  Multiple JSON result files for RepetitionsRunGroups are merged with the
  JSONMerger. Custom merging for other RunGroups can be defined in the subclass.
  """

  FLATTEN = True

  @property
  def results_file_name(self) -> str:
    return f"{self.name}.json"

  @abc.abstractmethod
  def to_json(self, actions):
    """
    Override in subclasses.
    Returns json-serializable data.
    """
    return None

  def flatten_json_data(self, json_data):
    return flatten(json_data)

  class Scope(probes.Probe.Scope):

    def __init__(self, probe: JsonResultProbe, run: cb.runner.Runner):
      super().__init__(probe, run)
      self._json_data = None

    @property
    def probe(self) -> JsonResultProbe:
      return super().probe

    def to_json(self, actions):
      return self.probe.to_json(actions)

    def start(self, run):
      pass

    def stop(self, run):
      self._json_data = self.extract_json(run)

    def tear_down(self, run):
      return self.write_json(run, self._json_data)

    def extract_json(self, run: cb.runner.Run):
      with run.actions(f"Extracting Probe name={self.probe.name}") as actions:
        json_data = self.to_json(actions)
        assert json_data is not None, (
            "Probe name=={self.probe.name} produced no data")
        return json_data

    def write_json(self, run: cb.runner.Run, json_data):
      with run.actions(f"Writing Probe name={self.probe.name}") as actions:
        assert json_data is not None
        raw_file = self.results_file
        if self.probe.FLATTEN:
          raw_file = raw_file.with_suffix(".raw.json")
          flattened_file = self.results_file
          flat_json_data = self.flatten_json_data(json_data)
          with flattened_file.open("w") as f:
            json.dump(flat_json_data, f, indent=2)
        with raw_file.open("w") as f:
          json.dump(json_data, f, indent=2)
      if self.probe.FLATTEN:
        return (flattened_file, raw_file)
      return raw_file

    def flatten_json_data(self, json_data):
      return self.probe.flatten_json_data(json_data)

  def merge_repetitions(self, group: cb.runner.RepetitionsRunGroup):
    merger = JSONMerger()
    for run in group.runs:
      source_file = self.get_mergeable_result_file(run.results[self])
      assert source_file.is_file()
      with source_file.open("r") as f:
        merger.add(json.load(f))
    return self.write_group_result(group, merger.to_json())

  def get_mergeable_result_file(self, results):
    if isinstance(results, tuple):
      return pathlib.Path(results[0])
    return pathlib.Path(results)

  def write_group_result(self, group, merged_data):
    destination_path = group.get_probe_results_file(self)
    with destination_path.open("w") as f:
      json.dump(merged_data, f, indent=2)
    return destination_path


class Values:
  """
  A collection of values that is use as an accumulator in the JSONMerger.

  Values provides simple statistical getters if the collected values are
  ints or floats only.
  """

  @classmethod
  def from_json(cls, json_data):
    return cls(json_data["values"])

  def __init__(self, values=None):
    self.values = values or []

  def is_numeric(self):
    return all(isinstance(v, (int, float)) for v in self.values)

  @property
  def min(self):
    return min(self.values)

  @property
  def max(self):
    return max(self.values)

  @property
  def average(self):
    return sum(self.values) / len(self.values)

  @property
  def geomean(self) -> float:
    product = 1
    for value in self.values:
      product *= value
    return product**(1 / len(self.values))

  @property
  def stddev(self) -> float:
    """
    We're ignoring here any actual distribution of the data and use this as a
    rough estimate of the quality of the data
    """
    average = self.average
    variance = 0
    for value in self.values:
      variance += (average - value)**2
    variance /= len(self.values)
    return math.sqrt(variance)

  def append(self, value):
    self.values.append(value)

  def to_json(self):
    json_data = dict(values=self.values)
    if self.is_numeric():
      json_data["min"] = self.min
      average = json_data["average"] = self.average
      json_data["geomean"] = self.geomean
      json_data["max"] = self.max
      stddev = json_data["stddev"] = self.stddev
      if average == 0:
        json_data["stddevPercent"] = 0
      else:
        json_data["stddevPercent"] = (stddev / average) * 100
      return json_data
    # Simplify repeated non-numeric values
    if len(set(self.values)) == 1:
      return self.values[0]
    return json_data


# ========================================================================
class JSONFlat:
  """
  Creates a sorted flat list of (key-path, Values) from hierarchical data.

  Input: {"a" : {"aa1":1, "aa2":2}, "b": 12 }
  Output: [
    "a/aa1":  1,
    "a/aa2":  2,
    "b":     12,
  ]
  """

  @classmethod
  def flatten(cls, *merged_data, key=None):
    instance = cls(key)
    instance.append(*merged_data)
    return instance.data

  def __init__(self, key=None):
    self._accumulator = {}
    self._key_fn = key or (lambda path: "/".join(path))

  @property
  def data(self):
    items = sorted(self._accumulator.items(), key=lambda item: item[0])
    return dict(items)

  def append(self, *args, ignore_toplevel=False):
    toplevel_path = tuple()
    for merged_data in args:
      self._flatten(toplevel_path, merged_data, ignore_toplevel)

  def _is_leaf_item(self, item):
    if isinstance(item, (str, float, int, list)):
      return True
    if "values" in item and isinstance(item["values"], list):
      return True
    return False

  def _flatten(self, parent_path, data, ignore_toplevel=False):
    for name, item in data.items():
      path = parent_path + (name,)
      if self._is_leaf_item(item):
        if ignore_toplevel and parent_path == ():
          continue
        key = self._key_fn(path)
        assert isinstance(key, str)
        assert key not in self._accumulator, (
            f"Duplicate key='{key}' path={path}")
        self._accumulator[key] = item
      else:
        self._flatten(path, item)


def flatten(*merged_data, key=None):
  return JSONFlat.flatten(*merged_data, key=key)


# ========================================================================


class JSONMerger:
  """
  Merges hierarchical data into 1-level aggregated data;

  Input:
  data_1 ={
    "a": {
      "aa": 1.1,
      "ab": 2
    }
    "b": 2.1
  }
  data_2 = {
    "a": {
      "aa": 1.2
    }
    "b": 2.2,
    "c": 2
  }

  The merged data maps pathlib.Path() => Values():
  {
    pathlib.Path("a/aa"): Values(1.1, 1.2)
    pathlib.Path("a/ab"): Values(2)
    pathlib.Path("b"):    Values(2.1, 2.2)
    pathlib.Path("c"):    Values(2)
  }
  """

  @classmethod
  def from_merged_files(cls, files):
    merger = cls()
    for file in files:
      with file.open() as f:
        merger.merge_json_values(json.load(f))
    return merger

  @classmethod
  def merge(cls, *args):
    merger = cls()
    for data in args:
      merger.add(data)
    return merger

  def __init__(self):
    self._data = {}
    self._ignored_paths = set()

  @property
  def data(self):
    return self._data

  def merge_json_values(self,
                        json_data,
                        prefix_path=None,
                        merge_duplicate_paths=False):
    """Merge a previously serialized data object"""
    for path, data in json_data.items():
      if prefix_path:
        path = prefix_path / pathlib.Path(path)
      else:
        path = pathlib.Path(path)
      if path in self._ignored_paths:
        continue
      if path in self._data:
        if merge_duplicate_paths:
          values = self._data[path]
          for value in json_data["values"]:
            values.append(value)
        else:
          logging.debug(
              "Removing Values with the same key-path='%s'"
              "from multiple files.", path)
          del self._data[path]
          self._ignored_paths.add(path)
      else:
        self._data[path] = Values.from_json(data)

  def add(self, json_data):
    if isinstance(json_data, list):
      # Assume that top-level lists are repetitions of the same data
      for item in json_data:
        self._merge(item, pathlib.Path())
    else:
      self._merge(json_data, pathlib.Path())

  def _merge(self, json_data, parent_path):
    assert isinstance(json_data, dict)
    for key, value in json_data.items():
      path = parent_path / key
      if isinstance(value, dict):
        self._merge(value, path)
      else:
        if path in self._data:
          values = self._data[path]
        else:
          values = self._data[path] = Values()
        if isinstance(value, list):
          for v in value:
            values.append(v)
        else:
          values.append(value)

  def to_json(self, value_fn=None):
    json_data = {}
    # Make sure the data is always in the same order, independent of the input
    # order
    paths = sorted(self._data.keys())
    for path in paths:
      value = self._data[path]
      assert isinstance(value, Values)
      if value_fn is None:
        json_data[str(path)] = value.to_json()
      else:
        json_data[str(path)] = value_fn(value)
    return json_data


def merge(*args, value=None):
  return JSONMerger.merge(*args).to_json(value_fn=value)
