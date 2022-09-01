# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from pathlib import Path

from crossbench import helper, probes, runner, stories


class JetStream2Probe(probes.JsonResultProbe):
  """
  JetStream2-specific Probe.
  Extracts all JetStream2 times and scores.
  """
  NAME = "jetstream_2"
  IS_GENERAL_PURPOSE = False
  FLATTEN = False
  JS = """
  let results = Object.create(null);
  for (let benchmark of JetStream.benchmarks) {
    const data = { score: benchmark.score };
    if ("worst4" in benchmark) {
      data.firstIteration = benchmark.firstIteration;
      data.average = benchmark.average;
      data.worst4 = benchmark.worst4;
    } else if ("runTime" in benchmark) {
      data.runTime = benchmark.runTime;
      data.startupTime = benchmark.startupTime;
    }
    results[benchmark.plan.name] = data;
  };
  return results;
"""

  def to_json(self, actions):
    return actions.js(self.JS)

  def merge_stories(self, group: runner.StoriesRunGroup):
    merged = probes.json.JSONMerger.from_merged_files(
        story_group.results[self] for story_group in group.repetitions_groups)
    merged_json_file = self.write_group_result(group, merged.to_json())
    merged_csv_file = merged_json_file.with_suffix(".csv")
    self._json_to_csv(merged.data, merged_csv_file)
    return (merged_json_file, merged_csv_file)

  def _json_to_csv(self, merged_data, out_file):
    assert not out_file.exists()
    # "story_name" => [ metric_value_path, ...], ...
    grouped_by_story = helper.group_by(
        sorted(merged_data.keys(), key=lambda path: str(path).lower()),
        key=lambda path: path.parts[0])
    # ("metric_name", ...) => [ "story_name", ... ], ...
    grouped_by_metrics = helper.group_by(
        grouped_by_story.items(),
        key=lambda item: tuple(sorted(path.name for path in item[1])),
        value=lambda item: item[0])

    with out_file.open("w") as f:
      important_fields = ("score", "average")
      for field_names, story_names in grouped_by_metrics.items():
        # Make field_names mutable again.
        field_names = list(field_names)
        # Rearrange fields to have the important ones first.
        for important_field in reversed(important_fields):
          if important_field in field_names:
            field_names.remove(important_field)
            field_names.insert(0, important_field)
        f.write("Name\t" + ("\t".join(field_names)) + "\n")
        for suite_name in story_names:
          fields = (suite_name,
                    *(merged_data[Path(suite_name) / field_name].geomean
                      for field_name in field_names))
          f.write("\t".join(map(str, fields)))
          f.write("\n")


class JetStream2Story(stories.PressBenchmarkStory):
  NAME = "jetstream_2"
  PROBES = (JetStream2Probe,)
  URL = "https://browserbench.org/JetStream/"
  URL_LOCAL = "http://localhost:8000/"
  SUBSTORIES = (
      "WSL",
      "UniPoker",
      "uglify-js-wtb",
      "typescript",
      "tsf-wasm",
      "tagcloud-SP",
      "string-unpack-code-SP",
      "stanford-crypto-sha256",
      "stanford-crypto-pbkdf2",
      "stanford-crypto-aes",
      "splay",
      "segmentation",
      "richards-wasm",
      "richards",
      "regexp",
      "regex-dna-SP",
      "raytrace",
      "quicksort-wasm",
      "prepack-wtb",
      "pdfjs",
      "OfflineAssembler",
      "octane-zlib",
      "octane-code-load",
      "navier-stokes",
      "n-body-SP",
      "multi-inspector-code-load",
      "ML",
      "mandreel",
      "lebab-wtb",
      "json-stringify-inspector",
      "json-parse-inspector",
      "jshint-wtb",
      "HashSet-wasm",
      "hash-map",
      "gcc-loops-wasm",
      "gbemu",
      "gaussian-blur",
      "float-mm.c",
      "FlightPlanner",
      "first-inspector-code-load",
      "espree-wtb",
      "earley-boyer",
      "delta-blue",
      "date-format-xparb-SP",
      "date-format-tofte-SP",
      "crypto-sha1-SP",
      "crypto-md5-SP",
      "crypto-aes-SP",
      "crypto",
      "coffeescript-wtb",
      "chai-wtb",
      "cdjs",
      "Box2D",
      "bomb-workers",
      "Basic",
      "base64-SP",
      "babylon-wtb",
      "Babylon",
      "async-fs",
      "Air",
      "ai-astar",
      "acorn-wtb",
      "3d-raytrace-SP",
      "3d-cube-SP",
  )
  DEFAULT_PROBES = (JetStream2Probe,)

  def run(self, run):
    with run.actions("Setup") as actions:
      actions.navigate_to(self._url)
      if self._substories != self.SUBSTORIES:
        actions.wait_js_condition(("return JetStream && JetStream.benchmarks "
                                   "&& JetStream.benchmarks.length > 0;"),
                                  helper.wait_range(0.1, 10))
        actions.js(
            """
        let benchmarks = arguments[0];
        JetStream.benchmarks = JetStream.benchmarks.filter(
            benchmark => benchmarks.includes(benchmark.name));
        """,
            arguments=[self._substories])
      actions.wait_js_condition(
          """
        return document.querySelectorAll("#results>.benchmark").length > 0;
      """, helper.wait_range(0.5, 10))
    with run.actions("Run") as actions:
      actions.js("JetStream.start()")
      actions.wait(2 * len(self._substories))
      actions.wait_js_condition(
          """
        let summaryElement = document.getElementById("result-summary");
        return (summaryElement.classList.contains("done"));
        """, helper.wait_range(1, 60 * 20))


class JetStream2Runner(runner.PressBenchmarkStoryRunner):
  """
  Benchmark runner for JetStream 2.

  See https://browserbench.org/JetStream/ for more details.
  """

  NAME = "jetstream_2"
  DEFAULT_STORY_CLS = JetStream2Story

  def __init__(self, *args, stories=None, **kwargs):
    if isinstance(stories, self.DEFAULT_STORY_CLS):
      stories = [stories]
    for story in stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS)
    super().__init__(*args, stories=stories, **kwargs)
