# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import crossbench as cb
import crossbench.benchmarks as bm

from . import BaseBenchmarkTestCase, PressBenchmarkTestCaseMixin


class MotionMark2Test(BaseBenchmarkTestCase, PressBenchmarkTestCaseMixin):

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
                      }
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
    stories = bm.motionmark.MotionMark12Story.from_names(['Multiply'])
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
        use_checklist=False,
        platform=self.platform,
        repetitions=repetitions)
    runner.run()
    for browser in self.browsers:
      self.assertEqual(len(browser.url_list), repetitions)
      self.assertIn(bm.motionmark.MotionMark12Probe.JS, browser.js_list)
