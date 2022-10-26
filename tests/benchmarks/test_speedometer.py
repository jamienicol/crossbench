# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from unittest import mock
import crossbench as cb
import crossbench.benchmarks as bm

from tests.benchmarks import helper


class Speedometer2Test(helper.PressBaseBenchmarkTestCase):


  @property
  def benchmark_cls(self):
    return bm.speedometer.Speedometer20Benchmark

  def test_story_filtering_cli_args_all(self):
    stories = bm.speedometer.Speedometer20Story.default(separate=True)
    args = mock.Mock()
    args.stories = "all"
    stories_all = self.benchmark_cls.stories_from_cli_args(args)
    self.assertListEqual(
        [story.name for story in stories],
        [story.name for story in stories_all],
    )

  def test_story_filtering(self):
    with self.assertRaises(ValueError):
      bm.speedometer.Speedometer20Story.from_names([])
    stories = bm.speedometer.Speedometer20Story.default(separate=False)
    self.assertEqual(len(stories), 1)

    with self.assertRaises(ValueError):
      bm.speedometer.Speedometer20Story.from_names([], separate=True)
    stories = bm.speedometer.Speedometer20Story.default(separate=True)
    self.assertEqual(
        len(stories), len(bm.speedometer.Speedometer20Story.SUBSTORIES))

  def test_story_filtering_regexp_invalid(self):
    with self.assertRaises(ValueError):
      self.story_filter(".*", separate=True).stories

  def test_story_filtering_regexp(self):
    stories = bm.speedometer.Speedometer20Story.default(separate=True)
    stories_b = self.story_filter([".*"], separate=True).stories
    self.assertListEqual(
        [story.name for story in stories],
        [story.name for story in stories_b],
    )

  def test_run(self):
    repetitions = 3
    iterations = 2
    stories = bm.speedometer.Speedometer20Story.from_names(
        ['VanillaJS-TodoMVC'])
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
        use_checklist=False,
        platform=self.platform,
        repetitions=repetitions)
    runner.run()
    for browser in self.browsers:
      self.assertEqual(len(browser.url_list), repetitions)
      self.assertIn(bm.speedometer.Speedometer20Probe.JS, browser.js_list)
