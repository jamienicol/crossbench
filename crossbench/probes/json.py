# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import json
import csv
import pathlib
from typing import Dict, TYPE_CHECKING, Union

import crossbench as cb
if TYPE_CHECKING:
  import crossbench.runner
from crossbench.probes import base
import crossbench.probes.helper as helper


class JsonResultProbe(base.Probe, metaclass=abc.ABCMeta):
  """
  Abstract Probe that stores a JSON result extracted by the `to_json` method

  Tje `to_json` is provided by subclasses. A typical examples includes just
  running a JS script on the page.
  Multiple JSON result files for RepetitionsRunGroups are merged with the
  ValuesMerger. Custom merging for other RunGroups can be defined in the subclass.
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
    return helper.Flatten(json_data).data

  class Scope(base.Probe.Scope):

    def __init__(self, probe: JsonResultProbe, run: cb.runner.Run):
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
      with run.actions(f"Writing Probe name={self.probe.name}"):
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

  def merge_repetitions(
      self,
      group: cb.runner.RepetitionsRunGroup,
  ) -> base.ProbeResultType:
    merger = helper.ValuesMerger()
    for run in group.runs:
      source_file = self.get_mergeable_result_file(run.results[self])
      assert source_file.is_file()
      with source_file.open("r") as f:
        merger.add(json.load(f))
    return self.write_group_result(group, merger)

  def get_mergeable_result_file(self, results):
    if isinstance(results, tuple):
      return pathlib.Path(results[0])
    return pathlib.Path(results)

  def write_group_result(self,
                         group,
                         merged_data: Union[Dict, helper.ValuesMerger],
                         write_csv=False,
                         value_fn=None) -> base.ProbeResultType:
    merged_json_path = group.get_probe_results_file(self)
    with merged_json_path.open("w") as f:
      if isinstance(merged_data, dict):
        json.dump(merged_data, f, indent=2)
      else:
        json.dump(merged_data.to_json(), f, indent=2)

    if not write_csv:
      return merged_json_path

    if not isinstance(merged_data, helper.ValuesMerger):
      raise ValueError("write_csv is only supported for ValuesMerger, "
                       f"but found {type(merged_data)}'.")

    if not value_fn:
      value_fn = lambda value: value.geomean

    return self.write_group_csv_result(merged_data, merged_json_path, value_fn)

  def write_group_csv_result(self, merged_data: helper.ValuesMerger,
                             merged_json_path: pathlib.Path, value_fn):
    merged_csv_path = merged_json_path.with_suffix(".csv")
    assert not merged_csv_path.exists()
    with merged_csv_path.open("w", newline='', encoding='utf-8') as f:
      csv.writer(f, delimiter="\t").writerows(merged_data.to_csv(value_fn))

    return {"json": merged_json_path, "csv": merged_csv_path}
