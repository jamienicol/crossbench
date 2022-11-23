# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from unittest import mock
import crossbench as cb
import crossbench.benchmarks as bm

from tests.benchmarks import helper

import sys
import pytest


class JetStream2Test(helper.PressBaseBenchmarkTestCase):

  @property
  def benchmark_cls(self):
    return bm.jetstream.JetStream2Benchmark

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
      self.assertIn(bm.jetstream.JetStream2Probe.JS, browser.js_list)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
