# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import csv
import json
import pathlib
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Union

import crossbench
from crossbench.probes import helper
from crossbench.probes import base

#TODO: fix imports
cb = crossbench
if TYPE_CHECKING:
  import crossbench.runner


class JsonResultProbe(base.Probe, metaclass=abc.ABCMeta):
  """
  Abstract Probe that stores a JSON result extracted by the `to_json` method

  Tje `to_json` is provided by subclasses. A typical examples includes just
  running a JS script on the page.
  Multiple JSON result files for RepetitionsRunGroups are merged with the
  ValuesMerger. Custom merging for other RunGroups can be defined in the
  subclass.
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

  def process_json_data(self, json_data):
    return json_data

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
      self._json_data = self.process_json_data(self._json_data)
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
          with flattened_file.open("w", encoding="utf-8") as f:
            json.dump(flat_json_data, f, indent=2)
        with raw_file.open("w", encoding="utf-8") as f:
          json.dump(json_data, f, indent=2)
      if self.probe.FLATTEN:
        return (flattened_file, raw_file)
      return raw_file

    def process_json_data(self, json_data):
      return self.probe.process_json_data(json_data)

    def flatten_json_data(self, json_data):
      return self.probe.flatten_json_data(json_data)

  def merge_repetitions(
      self,
      group: cb.runner.RepetitionsRunGroup,
  ) -> base.ProbeResultType:
    merger = helper.ValuesMerger()
    for run in group.runs:
      if self not in run.results:
        raise Exception(f"Probe {self.NAME} produced no data to merge.")
      source_file = self.get_mergeable_result_file(run.results[self])
      assert source_file.is_file()
      with source_file.open(encoding="utf-8") as f:
        merger.add(json.load(f))
    return self.write_group_result(group, merger, write_csv=True)

  def merge_browsers_csv_files(self, group: cb.runner.BrowsersRunGroup
                              ) -> pathlib.Path:
    csv_files: List[pathlib.Path] = []
    headers: List[str] = []
    for story_group in group.story_groups:
      csv_files.append(story_group.results[self]["csv"])
      headers.append(story_group.browser.unique_name)
    merged_table = helper.merge_csv(csv_files)
    merged_json_path = group.get_probe_results_file(self)
    merged_csv_path = merged_json_path.with_suffix(".csv")
    assert not merged_csv_path.exists()
    with merged_csv_path.open("w", newline="", encoding="utf-8") as f:
      csv.writer(f, delimiter="\t").writerows(merged_table)
    return merged_csv_path

  def get_mergeable_result_file(self, results):
    if isinstance(results, tuple):
      return pathlib.Path(results[0])
    return pathlib.Path(results)

  def write_group_result(self,
                         group: cb.runner.RunGroup,
                         merged_data: Union[Dict, helper.ValuesMerger],
                         write_csv: bool = False,
                         value_fn: Optional[Callable[[Any], Any]] = None
                        ) -> base.ProbeResultType:
    merged_json_path = group.get_probe_results_file(self)
    with merged_json_path.open("w", encoding="utf-8") as f:
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
      value_fn = value_geomean
    return self.write_group_csv_result(group, merged_data, merged_json_path,
                                       value_fn)

  def write_group_csv_result(self, group: cb.runner.RunGroup,
                             merged_data: helper.ValuesMerger,
                             merged_json_path: pathlib.Path,
                             value_fn: Callable[[Any], Any]):
    merged_csv_path = merged_json_path.with_suffix(".csv")
    assert not merged_csv_path.exists()
    with merged_csv_path.open("w", newline="", encoding="utf-8") as f:
      writer = csv.writer(f, delimiter="\t")
      csv_data = merged_data.to_csv(value_fn, group.csv_header)
      writer.writerows(csv_data)
    return {"json": merged_json_path, "csv": merged_csv_path}


def value_geomean(value):
  return value.geomean
