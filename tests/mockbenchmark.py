# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import pathlib
import psutil
from typing import List, Optional
from pyfakefs import fake_filesystem_unittest

import crossbench as cb
from crossbench import cli
from crossbench import helper

FlagsInitialDataType = cb.flags.Flags.InitialDataType

GiB = 1014**3

ActivePlatformClass = type(helper.platform)


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


mock_platform = MockPlatform()


class MockBrowser(cb.browsers.Browser):
  BIN_PATH: pathlib.Path = pathlib.Path("/")
  VERSION = "100.22.33.44"

  @classmethod
  def setup_fs(cls, fs, bin_name="Chrome"):
    if helper.platform.is_macos:
      fs.create_file(cls.BIN_PATH / "Contents" / "MacOS" / bin_name)
    else:
      fs.create_file(cls.BIN_PATH)

  def __init__(self,
               label: str,
               path: Optional[pathlib.Path] = None,
               browser_name:str = "chrome",
               *args,
               **kwargs):
    assert self.BIN_PATH
    path = path or pathlib.Path(self.BIN_PATH)
    kwargs["type"] = browser_name
    super().__init__(label, path, *args, **kwargs)
    self.url_list: List[str] = []
    self.js_list: List[str] = []
    self.js_side_effect: List[str] = []
    self.run_js_side_effect: List[str] = []
    self.did_run: bool = False
    self.clear_cache_dir: bool = False
    self.js_flags: cb.flags.JSFlags = cb.flags.JSFlags()

  def clear_cache(self, runner: cb.runner.Runner):
    pass

  def start(self, run: cb.runner.Run):
    assert not self._is_running
    self._is_running = True
    self.did_run = True
    self.run_js_side_effect = list(self.js_side_effect)

  def force_quit(self):
    # Assert that start() was called before force_quit()
    assert self._is_running
    self._is_running = False

  def _extract_version(self):
    return self.VERSION

  def show_url(self, runner, url):
    self.url_list.append(url)

  def js(self, runner, script, timeout=None, arguments=()):
    self.js_list.append(script)
    if self.js_side_effect is None:
      return None
    assert self.run_js_side_effect, (
        "Not enough mock js_side_effect available. "
        "Please add another js_side_effect entry for "
        f"arguments={arguments} \n"
        f"Script: {script}")
    return self.run_js_side_effect.pop(0)


class MockChromeStable(MockBrowser):
  if helper.platform.is_macos:
    BIN_PATH = pathlib.Path("/Applications/Google Chrome.app")
  else:
    BIN_PATH = pathlib.Path("/usr/bin/chrome")


class MockChromeDev(MockBrowser):
  if helper.platform.is_macos:
    BIN_PATH = pathlib.Path("/Applications/Google Chrome Dev.app")
  else:
    BIN_PATH = pathlib.Path("/usr/bin/chrome-dev")


class MockChromeCanary(MockBrowser):
  if helper.platform.is_macos:
    BIN_PATH = pathlib.Path("/Applications/Google Chrome Canary.app")
  else:
    BIN_PATH = pathlib.Path("/usr/bin/chrome-canary")


class MockSafari(MockBrowser):
  if helper.platform.is_macos:
    BIN_PATH = pathlib.Path("/Applications/Safari.app")
  else:
    BIN_PATH = pathlib.Path('/unsupported-platform/Safari')

  @classmethod
  def setup_fs(cls, fs):
    return super().setup_fs(fs, bin_name="Safari")


class MockStory(cb.stories.Story):
  pass


class MockBenchmark(cb.benchmarks.base.SubStoryBenchmark):
  DEFAULT_STORY_CLS = MockStory


class MockCLI(cli.CrossBenchCLI):

  def _get_runner(self, args, benchmark, env_config, env_validation_mode):
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
    self.setUpPyfakefs(modules_to_reload=[cb])
    MockChromeDev.setup_fs(self.fs)
    MockChromeStable.setup_fs(self.fs)
    self.platform = mock_platform
    self.out_dir = pathlib.Path("tmp/results/test")
    self.out_dir.parent.mkdir(parents=True)
    self.browsers = [
        MockChromeDev("dev", platform=self.platform),
        MockChromeStable("stable", platform=self.platform)
    ]
