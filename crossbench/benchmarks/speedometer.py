# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import json
import pathlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  import crossbench as cb

import crossbench.probes as probes
import crossbench.stories as stories
import crossbench.helper as helper
import crossbench.benchmarks.base as benchmarks


class Speedometer20Probe(probes.JsonResultProbe):
  """
  Speedometer2-specific probe.
  Extracts all speedometer times and scores.
  """
  NAME = "speedometer_2.0"
  IS_GENERAL_PURPOSE = False
  JS = "return globalThis.suiteValues;"

  def to_json(self, actions):
    return actions.js(self.JS)

  def flatten_json_data(self, json_data):
    # json_data may contain multiple iterations, merge those first
    assert isinstance(json_data, list)
    merged = probes.json.merge(
        *json_data, value=lambda values: values.geomean)
    return probes.json.flatten(merged)

  def merge_stories(self, group: cb.runner.StoriesRunGroup):
    merged = probes.json.JSONMerger.from_merged_files(
        story_group.results[self] for story_group in group.repetitions_groups)
    merged_json_file = group.get_probe_results_file(self)
    with merged_json_file.open("w") as f:
      json.dump(merged.to_json(), f, indent=2)
    merged_csv_file = merged_json_file.with_suffix(".csv")
    self._json_to_csv(merged.data, merged_csv_file)
    return (merged_json_file, merged_csv_file)

  def _json_to_csv(self, merged_data, out_file):
    assert not out_file.exists()
    # In: "tests/Angular2-TypeScript-TodoMVC/tests/Adding100Items/tests/Async"
    # Out: "Angular2-TypeScript-TodoMVC/Adding100Items/Async"
    merged_data = {
        pathlib.Path(str(k).replace("tests/", "")): v
        for k, v in merged_data.items()
    }
    # "suite_name" => (metric_value_path, ...), ...
    grouped_by_suite = helper.group_by(
        sorted(merged_data.keys(), key=lambda path: str(path).lower()),
        key=lambda path: path.parts[0])
    # Sort summary metrics ("total"...) last
    grouped_by_suite = dict(
        sorted(
            grouped_by_suite.items(),
            key=lambda item: ("-" not in item[0], item[0].lower())))

    with out_file.open("w") as f:
      for suite_name, metric_paths in grouped_by_suite.items():
        f.write(suite_name)
        if len(metric_paths) > 1:
          f.write("\n")
        for path in metric_paths:
          f.write(" ".join(path.parts[1:]))
          f.write("\t")
          f.write(str(merged_data[path].geomean))
          f.write("\n")


class Speedometer20Story(stories.PressBenchmarkStory):
  NAME = "speedometer_2.0"
  PROBES = (Speedometer20Probe,)
  URL = "https://browserbench.org/Speedometer2.0/InteractiveRunner.html"
  URL_LOCAL = "http://localhost:8000/InteractiveRunner.html"
  SUBSTORIES = (
      "VanillaJS-TodoMVC",
      "Vanilla-ES2015-TodoMVC",
      "Vanilla-ES2015-Babel-Webpack-TodoMVC",
      "React-TodoMVC",
      "React-Redux-TodoMVC",
      "EmberJS-TodoMVC",
      "EmberJS-Debug-TodoMVC",
      "BackboneJS-TodoMVC",
      "AngularJS-TodoMVC",
      "Angular2-TypeScript-TodoMVC",
      "VueJS-TodoMVC",
      "jQuery-TodoMVC",
      "Preact-TodoMVC",
      "Inferno-TodoMVC",
      "Elm-TodoMVC",
      "Flight-TodoMVC",
  )

  def __init__(self, is_live=True, substories=None, iterations=None):
    super().__init__(is_live=is_live, substories=substories, duration=30)
    self.iterations = iterations or 10

  def run(self, run: cb.runner.Run):
    with run.actions("Setup") as actions:
      actions.navigate_to(self._url)
      actions.wait_js_condition(
          """
        return globalThis.Suites !== undefined;
      """, helper.wait_range(0.5, 10))
      if self._substories != self.SUBSTORIES:
        actions.js(
            """
        let substories = arguments[0];
        Suites.forEach((suite) => {
          suite.disabled = substories.indexOf(suite.name) == -1;
        });
        """,
            arguments=[self._substories])
      actions.wait(0.5)
    with run.actions("Run") as actions:
      actions.js(
          """
        // Store all the results in the benchmarkClient
        globalThis.testDone = false;
        globalThis.suiteValues = [];
        const benchmarkClient = {
          didRunSuites(measuredValues) {
            globalThis.suiteValues.push(measuredValues);
          },
          didFinishLastIteration() {
            globalThis.testDone = true;
          }
        };
        const runner = new BenchmarkRunner(Suites, benchmarkClient);
        const iterationCount = arguments[0];
        runner.runMultipleIterations(iterationCount);
        """,
          arguments=[self.iterations])
      actions.wait(1 * len(self._substories))
      actions.wait_js_condition(
          "return globalThis.testDone",
          helper.wait_range(1, 10 +
                               2 * len(self._substories) * self.iterations))


class Speedometer20Runner(benchmarks.PressBenchmark):
  """
  Benchmark runner for Speedometer 2.0
  """
  NAME = "speedometer_2.0"
  DEFAULT_STORY_CLS = Speedometer20Story

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers)
    parser.add_argument(
        "--iterations",
        default=10,
        type=int,
        help="Number of iterations each Speedometer subtest is run "
        "within the same session. \n"
        "Note: --repeat restarts the whole benchmark, --iterations runs the"
        "same test tests n-times within the same session without the setup "
        "overhead of starting up a whole new browser.")
    return parser

  @classmethod
  def kwargs_from_cli(cls, args) -> dict:
    kwargs = super().kwargs_from_cli(args)
    kwargs["iterations"] = args.iterations
    return kwargs

  def __init__(self, stories=None, iterations=None):
    if isinstance(stories, self.DEFAULT_STORY_CLS):
      stories = [stories]
    elif stories is None:
      stories = self.DEFAULT_STORY_CLS.default()
    for story in stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS)
      if iterations:
        story.iterations = int(iterations)
    super().__init__(stories)
