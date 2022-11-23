# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from unittest import mock

import sys
from pathlib import Path

# Fix the path so that crossbench modules are importable
root_dir = Path(__file__).parents[2]
sys.path.insert(0, str(root_dir))

import crossbench as cb
from crossbench.benchmarks import speedometer
import crossbench.runner
import crossbench.env

from tests.benchmarks import helper

import pytest


class Speedometer2Test(helper.PressBaseBenchmarkTestCase):


  @property
  def benchmark_cls(self):
    return speedometer.Speedometer20Benchmark

  def test_story_filtering_cli_args_all_separate(self):
    stories = speedometer.Speedometer20Story.default(separate=True)
    args = mock.Mock()
    args.stories = "all"
    args.is_live = False
    args.separate = True
    stories_all = self.benchmark_cls.stories_from_cli_args(args)
    self.assertListEqual(
        [story.name for story in stories],
        [story.name for story in stories_all],
    )

  def test_story_filtering_cli_args_all(self):
    stories = speedometer.Speedometer20Story.default(separate=False)
    args = mock.Mock()
    args.stories = "all"
    args.is_live = False
    args.separate = False
    stories_all = self.benchmark_cls.stories_from_cli_args(args)
    self.assertEqual(len(stories), 1)
    self.assertEqual(len(stories_all), 1)
    story = stories[0]
    assert isinstance(story, speedometer.Speedometer20Story)
    self.assertEqual(story.name, "speedometer_2.0")
    story = stories_all[0]
    assert isinstance(story, speedometer.Speedometer20Story)
    self.assertEqual(story.name, "speedometer_2.0")
    self.assertEqual(story.url, speedometer.Speedometer20Story.URL_LOCAL)

    args.is_live = True
    args.separate = False
    stories_all = self.benchmark_cls.stories_from_cli_args(args)
    self.assertEqual(len(stories_all), 1)
    story = stories_all[0]
    assert isinstance(story, speedometer.Speedometer20Story)
    self.assertEqual(story.name, "speedometer_2.0")
    self.assertEqual(story.url, speedometer.Speedometer20Story.URL)

  def test_story_filtering(self):
    with self.assertRaises(ValueError):
      speedometer.Speedometer20Story.from_names([])
    stories = speedometer.Speedometer20Story.default(separate=False)
    self.assertEqual(len(stories), 1)

    with self.assertRaises(ValueError):
      speedometer.Speedometer20Story.from_names([], separate=True)
    stories = speedometer.Speedometer20Story.default(separate=True)
    self.assertEqual(
        len(stories), len(speedometer.Speedometer20Story.SUBSTORIES))

  def test_story_filtering_regexp_invalid(self):
    with self.assertRaises(ValueError):
      self.story_filter(".*", separate=True).stories  # pytype: disable=wrong-arg-types

  def test_story_filtering_regexp(self):
    stories = speedometer.Speedometer20Story.default(separate=True)
    stories_b = self.story_filter([".*"], separate=True).stories
    self.assertListEqual(
        [story.name for story in stories],
        [story.name for story in stories_b],
    )

  def test_run(self):
    repetitions = 3
    iterations = 2
    stories = speedometer.Speedometer20Story.from_names(['VanillaJS-TodoMVC'])
    example_story_data = {
        "tests": {
            "Adding100Items": {
                "tests": {
                    "Sync": 74.6000000089407,
                    "Async": 6.299999997019768
                },
                "total": 80.90000000596046
            },
            "CompletingAllItems": {
                "tests": {
                    "Sync": 22.600000008940697,
                    "Async": 5.899999991059303
                },
                "total": 28.5
            },
            "DeletingItems": {
                "tests": {
                    "Sync": 11.800000011920929,
                    "Async": 0.19999998807907104
                },
                "total": 12
            }
        },
        "total": 121.40000000596046
    }
    speedometer_probe_results = [{
        "tests": {story.name: example_story_data for story in stories},
        "total": 1000,
        "mean": 2000,
        "geomean": 3000,
        "score": 10
    } for i in range(iterations)]

    for browser in self.browsers:
      browser.js_side_effect = [
          True,  # Page is ready
          None,  # filter benchmarks
          None,  # Start running benchmark
          True,  # Wait until done
          speedometer_probe_results,
      ]
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)
    runner = cb.runner.Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=cb.env.HostEnvironmentConfig(),
        env_validation_mode=cb.env.ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions)
    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()
    for browser in self.browsers:
      urls = self.filter_data_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(speedometer.Speedometer20Probe.JS, browser.js_list)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
