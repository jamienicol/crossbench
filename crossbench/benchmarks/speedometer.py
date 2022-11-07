# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import csv
import pathlib
from typing import TYPE_CHECKING, Optional, Sequence, Tuple, List

import crossbench as cb
if TYPE_CHECKING:
  import crossbench.runner

import crossbench.probes.json as probes_json
import crossbench.probes.helper as probes_helper
import crossbench.stories
from crossbench import helper
import crossbench.benchmarks


def _probe_remove_tests_segments(path: Tuple[str, ...]):
  return "/".join(segment for segment in path if segment != "tests")


class Speedometer20Probe(probes_json.JsonResultProbe):
  """
  Speedometer2-specific probe.
  Extracts all speedometer times and scores.
  """
  NAME = "speedometer_2.0"
  IS_GENERAL_PURPOSE = False
  JS = "return globalThis.suiteValues;"

  def to_json(self, actions):
    return actions.js(self.JS)

  def flatten_json_data(self, json_data: Sequence):
    # json_data may contain multiple iterations, merge those first
    assert isinstance(json_data, list)
    merged = probes_helper.ValuesMerger(
        json_data, key_fn=_probe_remove_tests_segments).to_json(
            value_fn=lambda values: values.geomean)
    return probes_helper.Flatten(merged).data

  def merge_stories(self, group: cb.runner.StoriesRunGroup):
    merged = probes_helper.ValuesMerger.merge_json_files(
        repetitions_group.results[self]
        for repetitions_group in group.repetitions_groups)
    return self.write_group_result(group, merged, write_csv=True)

  def merge_browsers(self, group: cb.runner.BrowsersRunGroup):
    csv_files: List[pathlib.Path] = []
    headers: List[str] = []
    for story_group in group.story_groups:
      csv_files.append(story_group.results[self]["csv"])
      headers.append(story_group.browser.label)

    merged_table = probes_helper.merge_csv(csv_files)

    merged_json_path = group.get_probe_results_file(self)
    merged_csv_path = merged_json_path.with_suffix(".csv")
    assert not merged_csv_path.exists()
    with merged_csv_path.open("w", newline='', encoding='utf-8') as f:
      csv.writer(f, delimiter="\t").writerows(merged_table)


class Speedometer20Story(cb.stories.PressBenchmarkStory):
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

  def __init__(self,
               is_live=True,
               substories: Sequence[str] = (),
               iterations=10):
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
    with run.actions("Start Run") as actions:
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
    with run.actions("Wait") as actions:
      actions.wait(1 * len(self._substories))
      actions.wait_js_condition(
          "return globalThis.testDone",
          helper.wait_range(1, 10 +
                               2 * len(self._substories) * self.iterations))


class Speedometer20Benchmark(cb.benchmarks.PressBenchmark):
  """
  Benchmark runner for Speedometer 2.0
  """
  NAME = "speedometer_2.0"
  DEFAULT_STORY_CLS = Speedometer20Story

  @classmethod
  def add_cli_parser(cls, subparsers,
                     aliases: Sequence[str] = ()) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers, aliases)
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
    kwargs["iterations"] = int(args.iterations)
    return kwargs

  def __init__(self,
               stories: Optional[Sequence[Speedometer20Story]] = None,
               is_live: bool = True,
               iterations: Optional[int] = None):
    if stories is None:
      stories = self.DEFAULT_STORY_CLS.default()
    for story in stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS)
      if iterations is not None:
        assert iterations >= 1
        story.iterations = iterations
    super().__init__(stories, is_live)
