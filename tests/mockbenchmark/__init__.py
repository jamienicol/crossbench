# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import pathlib
import psutil
from typing import List, Optional, Tuple, Type
from pyfakefs import fake_filesystem_unittest

import crossbench as cb
from crossbench import cli
from crossbench import helper

from . import browser

FlagsInitialDataType = cb.flags.Flags.InitialDataType

GiB = 1014**3

ActivePlatformClass: Type[cb.helper.Platform] = type(cb.helper.platform)


class MockPlatform(ActivePlatformClass):

  def __init__(self, is_battery_powered=False):
    self._is_battery_powered = is_battery_powered

  @property
  def is_battery_powered(self):
    return self._is_battery_powered

  def disk_usage(self, path: pathlib.Path):
    return psutil._common.sdiskusage(
        total=GiB * 100, used=20 * GiB, free=80 * GiB, percent=20)

  def cpu_usage(self):
    return 0.1

  def system_details(self):
    return {"CPU": "20-core 3.1 GHz"}

  def sleep(self, duration):
    pass

  def processes(self, attrs=[]):
    return []

  def process_children(self, parent_pid: int, recursive=False):
    return []

  def foreground_process(self):
    return None


mock_platform = MockPlatform()  # pytype: disable=not-instantiable


class MockStory(cb.stories.Story):
  pass


class MockBenchmark(cb.benchmarks.base.SubStoryBenchmark):
  DEFAULT_STORY_CLS = MockStory


class MockCLI(cli.CrossBenchCLI):

  def _get_runner(self, args, benchmark, env_config, env_validation_mode):
    if not args.out_dir:
      # Use stable mock out dir
      args.out_dir = pathlib.Path("/results")
      assert not args.out_dir.exists()
    runner_kwargs = self.RUNNER_CLS.kwargs_from_cli(args)
    self.runner = self.RUNNER_CLS(
        benchmark=benchmark,
        env_config=env_config,
        env_validation_mode=env_validation_mode,
        **runner_kwargs,
        # Use custom platform
        platform=mock_platform)
    return self.runner


class BaseCrossbenchTestCase(
    fake_filesystem_unittest.TestCase, metaclass=abc.ABCMeta):

  def setUp(self):
    self.setUpPyfakefs(modules_to_reload=[cb, browser])
    for mock_browser_cls in browser.ALL:
      mock_browser_cls.setup_fs(self.fs)
      self.assertTrue(mock_browser_cls.APP_PATH.exists())
    self.platform = mock_platform
    self.out_dir = pathlib.Path("/tmp/results/test")
    self.out_dir.parent.mkdir(parents=True)
    self.browsers = [
        browser.MockChromeDev("dev", platform=self.platform),
        browser.MockChromeStable("stable", platform=self.platform)
    ]
