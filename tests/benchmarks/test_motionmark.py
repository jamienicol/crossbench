# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from unittest import mock
import crossbench as cb
import crossbench.benchmarks as bm

from tests.benchmarks import helper

import sys
import pytest


class MotionMark2Test(helper.PressBaseBenchmarkTestCase):

  @property
  def benchmark_cls(self):
    return bm.motionmark.MotionMark12Benchmark

  EXAMPLE_PROBE_DATA = [{
      "testsResults": {
          "MotionMark": {
              "Multiply": {
                  "complexity": {
                      "complexity": 1169.7666313745012,
                      "stdev": 2.6693101402239985,
                      "bootstrap": {
                          "confidenceLow": 1154.0859381321234,
                          "confidenceHigh": 1210.464520355893,
                          "median": 1180.8987652049277,
                          "mean": 1163.0061487765158,
                          "confidencePercentage": 0.8
                      },
                      "segment1": [[1, 16.666666666666668],
                                   [1, 16.666666666666668]],
                      "segment2": [[1, 6.728874992470971],
                                   [3105, 13.858528114770454]]
                  },
                  "controller": {
                      "score": 1168.106104032434,
                      "average": 1168.106104032434,
                      "stdev": 37.027504395081785,
                      "percent": 3.1698750881669624
                  },
                  "score": 1180.8987652049277,
                  "scoreLowerBound": 1154.0859381321234,
                  "scoreUpperBound": 1210.464520355893
              }
          }
      },
      "score": 1180.8987652049277,
      "scoreLowerBound": 1154.0859381321234,
      "scoreUpperBound": 1210.464520355893
  }]

  def test_run(self):
    stories = bm.motionmark.MotionMark12Story.from_names(["Multiply"])
    for browser in self.browsers:
      browser.js_side_effect = [
          True,  # Page is ready
          1,  # NOF enabled benchmarks
          None,  # Start running benchmark
          True,  # Wait until done
          self.EXAMPLE_PROBE_DATA
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
      self.assertIn(bm.motionmark.MotionMark12Probe.JS, browser.js_list)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
