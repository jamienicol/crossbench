# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import pathlib
import pyfakefs.fake_filesystem_unittest

import crossbench as cb
import crossbench.benchmarks as bm

from . import mockbenchmark


class BaseRunnerTest(
    pyfakefs.fake_filesystem_unittest.TestCase, metaclass=abc.ABCMeta):

  def setUp(self):
    self.setUpPyfakefs(modules_to_reload=[cb, mockbenchmark])
    mockbenchmark.MockBrowserDev.setup_fs(self.fs)
    mockbenchmark.MockBrowserStable.setup_fs(self.fs)
    self.platform = mockbenchmark.mock_platform
    self.out_dir = pathlib.Path("tmp/results/test")
    self.out_dir.parent.mkdir(parents=True)
    self.browsers = [
        mockbenchmark.MockBrowserDev("dev", platform=self.platform),
        mockbenchmark.MockBrowserStable("stable", platform=self.platform)
    ]


class TestPageLoadBenchmark(BaseRunnerTest):
  BENCHMARK = bm.loading.PageLoadBenchmark

  def test_default_stories(self):
    stories = bm.loading.LivePage.from_names(["all"])
    self.assertGreater(len(stories), 1)
    for story in stories:
      self.assertIsInstance(story, bm.loading.LivePage)

  def test_combined_stories(self):
    stories = bm.loading.LivePage.from_names(["all"], separate=False)
    self.assertEqual(len(stories), 1)
    combined = stories[0]
    self.assertIsInstance(combined, bm.loading.CombinedPage)

  def test_filter_by_name(self):
    for page in bm.loading.PAGE_LIST:
      stories = bm.loading.LivePage.from_names([page.name])
      self.assertListEqual(stories, [page])
    self.assertListEqual(bm.loading.LivePage.from_names([]), [])

  def test_filter_by_name_with_duration(self):
    pages = bm.loading.PAGE_LIST
    filtered_pages = bm.loading.LivePage.from_names(
        [pages[0].name, pages[1].name, '1001'])
    self.assertListEqual(filtered_pages, [pages[0], pages[1]])
    self.assertEqual(filtered_pages[0].duration, pages[0].duration)
    self.assertEqual(filtered_pages[1].duration, 1001)

  def test_page_by_url(self):
    url1 = "http:://example.com/test1"
    url2 = "http:://example.com/test2"
    stories = bm.loading.LivePage.from_names([url1, url2])
    self.assertEqual(len(stories), 2)
    self.assertEqual(stories[0].url, url1)
    self.assertEqual(stories[1].url, url2)

  def test_page_by_url_combined(self):
    url1 = "http:://example.com/test1"
    url2 = "http:://example.com/test2"
    stories = bm.loading.LivePage.from_names([url1, url2], separate=False)
    self.assertEqual(len(stories), 1)
    combined = stories[0]
    self.assertIsInstance(combined, bm.loading.CombinedPage)

  def test_run(self):
    stories = bm.loading.PAGE_LIST
    benchmark = self.BENCHMARK(stories)
    self.assertTrue(len(benchmark.describe()) > 0)
    runner = cb.runner.Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        use_checklist=False,
        platform=self.platform)
    runner.run()
    self.assertEqual(self.browsers[0].url_list,
                     [story.url for story in stories])
    self.assertEqual(self.browsers[1].url_list,
                     [story.url for story in stories])
    self.assertTrue(self.browsers[0].did_run)
    self.assertTrue(self.browsers[1].did_run)


class Speedometer2Test(BaseRunnerTest):
  BENCHMARK = bm.speedometer.Speedometer20Benchmark

  def test_story_filtering(self):
    stories = bm.speedometer.Speedometer20Story.from_names([])
    self.assertEqual(len(stories), 1)
    stories = bm.speedometer.Speedometer20Story.from_names([], separate=True)
    self.assertEqual(len(stories),
                     len(bm.speedometer.Speedometer20Story.SUBSTORIES))
    stories_b = bm.speedometer.Speedometer20Story.from_names(".*",
                                                             separate=True)
    self.assertListEqual(
        [story.name for story in stories],
        [story.name for story in stories_b],
    )
    stories_c = bm.speedometer.Speedometer20Story.from_names([".*"],
                                                             separate=True)
    self.assertListEqual(
        [story.name for story in stories],
        [story.name for story in stories_c],
    )

  def test_invalid_story_names(self):
    with self.assertRaises(Exception):
      # Only one regexp entry will work
      bm.speedometer.Speedometer20Story.from_names([".*", 'a'], separate=True)


  def test_run(self):
    repetitions = 3
    iterations = 2
    stories = bm.speedometer.Speedometer20Story.from_names(['VanillaJS-TodoMVC'])
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
        "tests": {story.name: example_story_data
                  for story in stories},
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
    benchmark = self.BENCHMARK(stories)
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


class JetStream2Test(BaseRunnerTest):
  BENCHMARK = bm.jetstream.JetStream2Benchmark

  def test_run(self):
    stories = bm.jetstream.JetStream2Story.from_names(['WSL'])
    example_story_data = {'firstIteration': 1, 'average': 0.1, 'worst4': 1.1}
    jetstream_probe_results = {
        story.name: example_story_data for story in stories
    }
    for browser in self.browsers:
      browser.js_side_effect = [
          True,  # Page is ready
          None,  # filter benchmarks
          True,  # UI is updated and ready,
          None,  # Start running benchmark
          True,  # Wait until done
          jetstream_probe_results,
      ]
    repetitions = 3
    benchmark = self.BENCHMARK(stories)
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
      self.assertIn(bm.jetstream.JetStream2Probe.JS, browser.js_list)

class MotionMark2Test(BaseRunnerTest):
  BENCHMARK = bm.motionmark.MotionMark12Benchmark
