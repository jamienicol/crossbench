# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import itertools
import json
import pathlib

from crossbench import helper, probes, runner, stories


class MotionMark12Probe(probes.JsonResultProbe):
  """
  MotionMark-specific Probe.
  Extracts all MotionMark times and scores.
  """
  NAME = "motionmark_1.2"
  IS_GENERAL_PURPOSE = False
  FLATTEN = False
  JS = """
    return window.benchmarkRunnerClient.results.results;
  """

  def to_json(self, actions):
    return actions.js(self.JS)

  @staticmethod
  def filter(key, value):
    name = pathlib.Path(key).name
    if name.startswith("segment") or name == "data":
      return False
    return True

  def flatten_json_data(self, json_data):
    flat_data = probes.json.flatten(*json_data)
    flat_data = {
        k: v for k, v in flat_data.items() if MotionMark12Probe.filter(k, v)
    }
    return flat_data


class MotionMark12Story(stories.PressBenchmarkStory):
  NAME = "motionmark_1.2"
  PROBES = (MotionMark12Probe,)
  URL = "https://browserbench.org/MotionMark1.2/developer.html"
  URL_LOCAL = "http://localhost:8000/developer.html"
  ALL_STORIES = {
      "MotionMark": (
          "Multiply",
          "Canvas Arcs",
          "Leaves",
          "Paths",
          "Canvas Lines",
          "Images",
          "Design",
          "Suits",
      ),
      "HTML suite": (
          "CSS bouncing circles",
          "CSS bouncing clipped rects",
          "CSS bouncing gradient circles",
          "CSS bouncing blend circles",
          "CSS bouncing filter circles",
          # "CSS bouncing SVG images",
          "CSS bouncing tagged images",
          "Focus 2.0",
          "DOM particles, SVG masks",
          # "Composited Transforms",
      ),
      "Canvas suite": (
          "canvas bouncing clipped rects",
          "canvas bouncing gradient circles",
          # "canvas bouncing SVG images",
          # "canvas bouncing PNG images",
          "Stroke shapes",
          "Fill shapes",
          "Canvas put/get image data",
      ),
      "SVG suite": (
          "SVG bouncing circles",
          "SVG bouncing clipped rects",
          "SVG bouncing gradient circles",
          # "SVG bouncing SVG images",
          # "SVG bouncing PNG images",
      ),
      "Leaves suite": (
          "Translate-only Leaves",
          "Translate + Scale Leaves",
          "Translate + Opacity Leaves",
      ),
      "Multiply suite": (
          "Multiply: CSS opacity only",
          "Multiply: CSS display only",
          "Multiply: CSS visibility only",
      ),
      "Text suite": (
          "Design: Latin only (12 items)",
          "Design: CJK only (12 items)",
          "Design: RTL and complex scripts only (12 items)",
          "Design: Latin only (6 items)",
          "Design: CJK only (6 items)",
          "Design: RTL and complex scripts only (6 items)",
      ),
      "Suits suite": (
          "Suits: clip only",
          "Suits: shape only",
          "Suits: clip, shape, rotation",
          "Suits: clip, shape, gradient",
          "Suits: static",
      ),
      "3D Graphics": (
          "Triangles (WebGL)",
          # "Triangles (WebGPU)",
      ),
      "Basic canvas path suite": (
          "Canvas line segments, butt caps",
          "Canvas line segments, round caps",
          "Canvas line segments, square caps",
          "Canvas line path, bevel join",
          "Canvas line path, round join",
          "Canvas line path, miter join",
          "Canvas line path with dash pattern",
          "Canvas quadratic segments",
          "Canvas quadratic path",
          "Canvas bezier segments",
          "Canvas bezier path",
          "Canvas arcTo segments",
          "Canvas arc segments",
          "Canvas rects",
          "Canvas ellipses",
          "Canvas line path, fill",
          "Canvas quadratic path, fill",
          "Canvas bezier path, fill",
          "Canvas arcTo segments, fill",
          "Canvas arc segments, fill",
          "Canvas rects, fill",
          "Canvas ellipses, fill",
      )
  }
  SUBSTORIES = list(itertools.chain.from_iterable(ALL_STORIES.values()))

  def run(self, run):
    with run.actions("Setup") as actions:
      actions.navigate_to(self._url)
      actions.wait_js_condition(
          """return document.querySelector("tree > li") !== undefined""",
          helper.wait_range(0.1, 10))
      num_enabled = actions.js(
          """
        let benchmarks = arguments[0];
        const list = document.querySelectorAll(".tree li");
        let counter = 0;
        for (const row of list) {
          const name = row.querySelector("label.tree-label").textContent.trim();
          let checked = benchmarks.includes(name);
          const labels = row.querySelectorAll("input[type=checkbox]");
          for (const label of labels) {
            if (checked) {
              label.click()
              counter++;
            }
          }
        }
        return counter
        """,
          arguments=[self._substories])
      assert num_enabled > 0, "No tests were enabled"
      actions.wait(0.1)
    with run.actions("Run") as actions:
      actions.js("window.benchmarkController.startBenchmark()")
      actions.wait(2 * len(self._substories))
      actions.wait_js_condition(
          """
          return window.benchmarkRunnerClient.results._results != undefined
          """, helper.wait_range(5, 20 * len(self._substories)))


class MotionMark12Runner(runner.PressBenchmarkStoryRunner):
  """
  Benchmark runner for MotionMark 1.2.

  See https://browserbench.org/MotionMark1.2/ for more details.
  """

  NAME = "motionmark_1.2"
  DEFAULT_STORY_CLS = MotionMark12Story

  def __init__(self, *args, stories=None, **kwargs):
    if isinstance(stories, self.DEFAULT_STORY_CLS):
      stories = [stories]
    for story in stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS)
    super().__init__(*args, stories=stories, **kwargs)
