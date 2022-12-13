# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import csv
from typing import Type
from unittest import mock

from crossbench.benchmarks.jetstream import (JetStream2Benchmark,
                                             JetStream2Probe, JetStream2Story)
from crossbench.env import HostEnvironmentConfig, ValidationMode
from crossbench.runner import Runner
from tests.benchmarks import helper


class JetStream2BaseTestCase(
    helper.PressBaseBenchmarkTestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  def benchmark_cls(self) -> Type[JetStream2Benchmark]:
    pass

  @property
  @abc.abstractmethod
  def story_cls(self) -> Type[JetStream2Story]:
    pass

  @property
  @abc.abstractmethod
  def probe_cls(self) -> Type[JetStream2Probe]:
    pass

  def test_run(self):
    stories = self.story_cls.from_names(["WSL"])
    example_story_data = {"firstIteration": 1, "average": 0.1, "worst4": 1.1}
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
    runner = Runner(
        self.out_dir,
        self.browsers,
        benchmark,
        env_config=HostEnvironmentConfig(),
        env_validation_mode=ValidationMode.SKIP,
        platform=self.platform,
        repetitions=repetitions,
        throw=True)
    with mock.patch.object(self.benchmark_cls, "validate_url") as cm:
      runner.run()
    cm.assert_called_once()
    for browser in self.browsers:
      urls = self.filter_data_urls(browser.url_list)
      self.assertEqual(len(urls), repetitions)
      self.assertIn(self.probe_cls.JS, browser.js_list)

    with (self.out_dir /
          f"{self.probe_cls.NAME}.csv").open(encoding="utf-8") as f:
      csv_data = list(csv.DictReader(f, delimiter="\t"))
    self.assertDictEqual(csv_data[0], {
        'label': 'browser',
        'dev': 'Chrome',
        'stable': 'Chrome'
    })
    self.assertDictEqual(csv_data[1], {
        'label': 'version',
        'dev': '102.22.33.44',
        'stable': '100.22.33.44'
    })
    with self.assertLogs(level='INFO') as cm:
      for probe in runner.probes:
        probe.log_result_summary(runner)
    output = "\n".join(cm.output)
    self.assertIn("JetStream results", output)
    self.assertIn("102.22.33.44", output)
    self.assertIn("100.22.33.44", output)
