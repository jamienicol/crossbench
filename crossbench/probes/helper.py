# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
import csv
import json

import logging
import math
import pathlib
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

_KeyFnType = Callable[[Tuple[str, ...]], Optional[str]]


def _default_flatten_key_fn(path: Tuple[str, ...]) -> str:
  return "/".join(path)


class Flatten:
  """
  Creates a sorted flat list of (key-path, Values) from hierarchical data.

  input = {"a" : {"aa1":1, "aa2":2}, "b": 12 }
  Flatten(input).data == {
    "a/aa1":  1,
    "a/aa2":  2,
    "b":     12,
  }
  """
  _key_fn: _KeyFnType
  _accumulator: Dict[str, object]

  def __init__(self, *args: Dict, key_fn: Optional[_KeyFnType] = None):
    """_summary_

    Args:
        *args (optional): Optional hierarchical data to be flattened
        key_fn (optional): Maps property paths (Tuple[str,...]) to strings used
          as final result keys, or None to skip property paths.
    """
    self._accumulator = {}
    self._key_fn = key_fn or _default_flatten_key_fn
    self.append(*args)

  @property
  def data(self):
    items = sorted(self._accumulator.items(), key=lambda item: item[0])
    return dict(items)

  def append(self, *args: Dict, ignore_toplevel=False):
    toplevel_path: Tuple[str, ...] = tuple()
    for merged_data in args:
      self._flatten(toplevel_path, merged_data, ignore_toplevel)

  def _is_leaf_item(self, item):
    if isinstance(item, (str, float, int, list)):
      return True
    if "values" in item and isinstance(item["values"], list):
      return True
    return False

  def _flatten(self, parent_path: Tuple[str, ...], data, ignore_toplevel=False):
    for name, item in data.items():
      path = parent_path + (name,)
      if self._is_leaf_item(item):
        if ignore_toplevel and parent_path == ():
          continue
        key = self._key_fn(path)
        if key is None:
          continue
        assert isinstance(key, str)
        if key in self._accumulator:
          raise ValueError(f"Duplicate key='{key}' path={path}")
        self._accumulator[key] = item
      else:
        self._flatten(path, item)


class Values:
  """
  A collection of values that is use as an accumulator in the ValuesMerger.

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
    variance = 0.0
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


class ValuesMerger:
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

  The merged data maps str => Values():

  ValuesMerger(data_1, data_2).data == {
    "a/aa": Values(1.1, 1.2)
    "a/ab": Values(2)
    "b":    Values(2.1, 2.2)
    "c":    Values(2)
  }
  """

  @classmethod
  def merge_json_files(cls,
                       files: Iterator[pathlib.Path],
                       key_fn: Optional[_KeyFnType] = None):
    merger = cls(key_fn=key_fn)
    for file in files:
      with file.open() as f:
        merger.merge_values(json.load(f))
    return merger

  def __init__(self,
               *args: Union[Dict, List[Dict]],
               key_fn: Optional[_KeyFnType] = None):
    """Create a new ValuesMerger

    Args:
        *args (optional): Optional hierarchical data to be merged.
        key_fn (optional): Maps property paths (Tuple[str,...]) to strings used
          as keys to group/merge values, or None to skip property paths.
    """
    self._data: Dict[str, Values] = {}
    self._key_fn: _KeyFnType = key_fn or _default_flatten_key_fn
    self._ignored_keys: Set[str] = set()
    for data in args:
      self.add(data)

  @property
  def data(self):
    return self._data

  def merge_values(self,
                   data: Dict[str, Dict],
                   prefix_path: Tuple[str, ...] = (),
                   merge_duplicate_paths=False):
    """Merge a previously json-serialized ValuesMerger object"""
    for property_name, data in data.items():
      path = prefix_path + (property_name,)
      key = self._key_fn(path)
      if key is None or key in self._ignored_keys:
        continue
      if key in self._data:
        if merge_duplicate_paths:
          values = self._data[key]
          for value in data["values"]:
            values.append(value)
        else:
          logging.debug(
              "Removing Values with the same key-path='%s', key='%s"
              "from multiple files.", path, key)
          del self._data[key]
          self._ignored_keys.add(key)
      else:
        self._data[key] = Values.from_json(data)

  def add(self, data: Union[Dict, List[Dict]]):
    """ Merge "arbitrary" hierarchical data that ends up having primitive leafs.
    Anything that is not a dict is considered a leaf node.
    """
    if isinstance(data, list):
      # Assume that top-level lists are repetitions of the same data
      for item in data:
        self._merge(item)
    else:
      self._merge(data)

  def _merge(self, data, parent_path: Tuple[str, ...] = ()):
    assert isinstance(data, dict)
    for property_name, value in data.items():
      path = parent_path + (property_name,)
      key: Optional[str] = self._key_fn(path)
      if key is None:
        continue
      if isinstance(value, dict):
        self._merge(value, path)
      else:
        if key in self._data:
          values = self._data[key]
        else:
          values = self._data[key] = Values()
        if isinstance(value, list):
          for v in value:
            values.append(v)
        else:
          values.append(value)

  def to_json(self, value_fn=None):
    items = []
    for key, value in self._data.items():
      assert isinstance(value, Values)
      if value_fn is None:
        value = value.to_json()
      else:
        value = value_fn(value)
      items.append((key, value))
    # Make sure the data is always in the same order, independent of the input
    # order
    items.sort()
    return dict(items)

  def to_csv(self, value_fn=None):
    """
    Input: {
        "VanillaJS-TodoMVC/Adding100Items/Async": 1
        "VanillaJS-TodoMVC/Adding100Items/Sync": 2
        "Total": 3
      }
    output: [
      ["VanillaJS-TodoMVC"],
      ["Adding100Items"],
      ["Async", 1]
      [],
      ["Sync", 2]
      ["Total", 3]
    ]
    """
    converted = self.to_json(value_fn)
    lookup = {}
    toplevel = []
    for key, value in converted.items():
      path = None
      segments = key.split("/")
      for segment in segments:
        if path:
          path += "/" + segment
        else:
          path = segment
        if path not in lookup:
          lookup[path] = None
      if len(segments) == 1:
        toplevel.append(key)
      lookup[key] = value
    csv = []
    for path, value in lookup.items():
      if path in toplevel:
        continue
      name = path.split("/")[-1]
      if value is None:
        csv.append([name])
      else:
        csv.append([name, value])
    # Write toplevel entries last
    for key in toplevel:
      csv.append([key, lookup[key]])

    return csv


def _ljust(sequence, n, fillvalue=""):
  return sequence + ([fillvalue] * (n - len(sequence)))


def merge_csv(csv_files: Sequence[pathlib.Path],
              headers: Optional[List[str]] = None,
              delimiter: str = "\t"):
  """
  Merge multiple CSV files.
  File 1:
    Header,     Col Header 1.1, Col Header  1.2
    Row Header, Data 1.1,       Data 1.2
  File 2:
    Header,     Col Header 2.1, Col Header 2.2
    Row Header, Data 2.1,       Data 2.2

  The first Col has to contain the same data:

  Merged:
    Header,     Col Header 1.1, Col Header 1.2,  Col Header 2.1, Col Header 2.2
    Row Header, Data 1.1,       Data 1.2,        Data 2.1,       Data 2.2


  If no column header is available, filename_as_header=True can be used.

  Merged with file name header:
            , File 1,           , File 2,
  Row Header, Data 1.1, Data 1.2, Data 2.1, Data 2.2
  """
  # Fill in the header column taken from the first file
  table = []
  if headers:
    table_headers = [""]
  else:
    table_headers = []
  with csv_files[0].open() as first_file:
    for row in csv.reader(first_file, delimiter=delimiter):
      metric_name = row[0]
      table.append([metric_name])

  for csv_file in csv_files:
    with csv_file.open() as f:
      csv_data = list(csv.reader(f, delimiter=delimiter))
      # Find the max width
      max_rows_with_row_header = max([len(row) for row in csv_data])
      max_rows = max_rows_with_row_header - 1
      if headers:
        col_header = [headers.pop(0)]
        table_headers.extend(_ljust(col_header, max_rows))
      for table_row, row in zip(table, csv_data):
        metric_name = row[0]
        padded_row = _ljust(row[1:], max_rows)
        assert table_row[0] == metric_name, (f"{table_row[0]} != {metric_name}"
                                             f"\n{csv_data}\n{table}")
        table_row.extend(padded_row)

  if table_headers:
    return [table_headers] + table
  return table
