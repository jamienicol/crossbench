# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import crossbench as cb
import crossbench.benchmarks as bm

from tests.benchmarks import helper


class TestPageLoadBenchmark(helper.SubStoryTestCase):

  @property
  def benchmark_cls(self):
    return bm.loading.PageLoadBenchmark

  def test_default_stories(self):
    stories = self.story_filter(["all"]).stories
    self.assertGreater(len(stories), 1)
    for story in stories:
      self.assertIsInstance(story, bm.loading.LivePage)

  def test_combined_stories(self):
    stories = self.story_filter(["all"], separate=False).stories
    self.assertEqual(len(stories), 1)
    combined = stories[0]
    self.assertIsInstance(combined, bm.loading.CombinedPage)

  def test_filter_by_name(self):
    for page in bm.loading.PAGE_LIST:
      stories = self.story_filter([page.name]).stories
      self.assertListEqual(stories, [page])
    self.assertListEqual(self.story_filter([]).stories, [])

  def test_filter_by_name_with_duration(self):
    pages = bm.loading.PAGE_LIST
    filtered_pages = self.story_filter([pages[0].name, pages[1].name,
                                        '1001']).stories
    self.assertListEqual(filtered_pages, [pages[0], pages[1]])
    self.assertEqual(filtered_pages[0].duration, pages[0].duration)
    self.assertEqual(filtered_pages[1].duration, 1001)

  def test_page_by_url(self):
    url1 = "http:://example.com/test1"
    url2 = "http:://example.com/test2"
    stories = self.story_filter([url1, url2]).stories
    self.assertEqual(len(stories), 2)
    self.assertEqual(stories[0].url, url1)
    self.assertEqual(stories[1].url, url2)

  def test_page_by_url_combined(self):
    url1 = "http:://example.com/test1"
    url2 = "http:://example.com/test2"
    stories = self.story_filter([url1, url2], separate=False).stories
    self.assertEqual(len(stories), 1)
    combined = stories[0]
    self.assertIsInstance(combined, bm.loading.CombinedPage)

  def test_run(self):
    stories = bm.loading.PAGE_LIST
    benchmark = self.benchmark_cls(stories)
    self.assertTrue(len(benchmark.describe()) > 0)
    runner = cb.runner.Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        environment_config=cb.runner.HostEnvironmentConfig.ignore(),
        platform=self.platform)
    runner.run()
    self.assertEqual(self.browsers[0].url_list,
                     [story.url for story in stories])
    self.assertEqual(self.browsers[1].url_list,
                     [story.url for story in stories])
    self.assertTrue(self.browsers[0].did_run)
    self.assertTrue(self.browsers[1].did_run)
