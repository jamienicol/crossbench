# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

import crossbench as cb

import crossbench.probes.json
import crossbench.probes.helper
import crossbench.stories
from crossbench import helper
import crossbench.benchmarks


class JetStream2Probe(cb.probes.json.JsonResultProbe):
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
    data = actions.js(self.JS)
    assert len(data) > 0, "No benchmark data generated"
    return data

  def merge_stories(self, group: cb.runner.StoriesRunGroup):
    merged = cb.probes.helper.ValuesMerger.merge_json_files(
        story_group.results[self] for story_group in group.repetitions_groups)
    return self.write_group_result(group, merged, write_csv=True)


class JetStream2Story(cb.stories.PressBenchmarkStory):
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
    with run.actions("Start") as actions:
      actions.js("JetStream.start()")
    with run.actions("Wait Done") as actions:
      actions.wait(2 * len(self._substories))
      actions.wait_js_condition(
          """
        let summaryElement = document.getElementById("result-summary");
        return (summaryElement.classList.contains("done"));
        """, helper.wait_range(1, 60 * 20))


class JetStream2Benchmark(cb.benchmarks.PressBenchmark):
  """
  Benchmark runner for JetStream 2.

  See https://browserbench.org/JetStream/ for more details.
  """

  NAME = "jetstream_2"
  DEFAULT_STORY_CLS = JetStream2Story
