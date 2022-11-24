# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import logging
import pathlib
import re
import shlex
import stat
import tempfile
import urllib.error
import zipfile
from typing import TYPE_CHECKING, Any, Dict, Final, List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

import crossbench as cb
import crossbench.flags
from crossbench import helper
from crossbench.browsers.base import (BROWSERS_CACHE, Browser,
                                      convert_flags_to_label)
from crossbench.browsers.webdriver import WebdriverMixin

if TYPE_CHECKING:
  import crossbench.runner

FlagsInitialDataType = cb.flags.Flags.InitialDataType


class Chrome(Browser):
  DEFAULT_FLAGS = [
      "--no-default-browser-check",
      "--disable-sync",
      "--no-experiments",
      "--enable-crossbench",
      "--disable-extensions",
      "--no-first-run",
  ]

  @classmethod
  def default_path(cls) -> pathlib.Path:
    return cls.stable_path()

  @classmethod
  def stable_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Stable",
        macos=["Google Chrome.app"],
        linux=["google-chrome", "chrome"],
        win=["Google/Chrome/Application/chrome.exe"])

  @classmethod
  def beta_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Beta",
        macos=["Google Chrome Beta.app"],
        linux=["google-chrome-beta"],
        win=["Google/Chrome Beta/Application/chrome.exe"])

  @classmethod
  def dev_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Dev",
        macos=["Google Chrome Dev.app"],
        linux=["google-chrome-unstable"],
        win=["Google/Chrome Dev/Application/chrome.exe"])

  @classmethod
  def canary_path(cls) -> pathlib.Path:
    return helper.search_app_or_executable(
        "Chrome Canary",
        macos=["Google Chrome Canary.app"],
        win=["Google/Chrome SxS/Application/chrome.exe"])

  @classmethod
  def default_flags(cls, initial_data: FlagsInitialDataType = None):
    return cb.flags.ChromeFlags(initial_data)

  def __init__(self,
               label: str,
               path: pathlib.Path,
               js_flags: FlagsInitialDataType = None,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               platform: Optional[helper.Platform] = None):
    if cache_dir is None:
      self.cache_dir = pathlib.Path(
          tempfile.TemporaryDirectory(prefix="chrome").name)
      self.clear_cache_dir = True
    else:
      self.cache_dir = cache_dir
      self.clear_cache_dir = False
    super().__init__(label, path, type="chrome", platform=platform)
    assert not isinstance(js_flags, str), (
        f"js_flags should be a list, but got: {repr(js_flags)}")
    assert not isinstance(
        flags, str), (f"flags should be a list, but got: {repr(flags)}")
    self._flags: cb.flags.ChromeFlags = self.default_flags(Chrome.DEFAULT_FLAGS)
    self._flags.update(flags)
    self.js_flags.update(js_flags)
    self._stdout_log_file = None

  def _extract_version(self):
    version_string = self.platform.app_version(self.path)
    # Sample output: "Google Chrome 90.0.4430.212 dev" => "90.0.4430.212"
    return re.findall(r"[\d\.]+", version_string)[0]

  @property
  def is_headless(self) -> bool:
    return "--headless" in self._flags

  @property
  def chrome_log_file(self) -> pathlib.Path:
    assert self.log_file
    return self.log_file.with_suffix(".chrome.log")

  @property
  def js_flags(self) -> cb.flags.JSFlags:
    return self._flags.js_flags

  @property
  def features(self) -> cb.flags.ChromeFeatures:
    return self._flags.features

  def exec_apple_script(self, script):
    return self.platform.exec_apple_script(script)

  def details_json(self) -> Dict[str, Any]:
    details = super().details_json()
    if self.log_file:
      details["log"]["chrome"] = str(self.chrome_log_file)
      details["log"]["stdout"] = str(self.stdout_log_file)
    details["js_flags"] = tuple(self.js_flags.get_list())
    return details

  def _get_browser_flags(self, run) -> Tuple[str, ...]:
    js_flags_copy = self.js_flags.copy()
    js_flags_copy.update(run.extra_js_flags)

    flags_copy = self.flags.copy()
    flags_copy.update(run.extra_flags)
    flags_copy["--window-size"] = f"{self.width},{self.height}"
    if len(js_flags_copy):
      flags_copy["--js-flags"] = str(js_flags_copy)
    if self.cache_dir and self.cache_dir:
      flags_copy["--user-data-dir"] = str(self.cache_dir)
    if self.clear_cache_dir:
      flags_copy.set("--incognito")
    if self.log_file:
      flags_copy.set("--enable-logging")
      flags_copy["--log-file"] = str(self.chrome_log_file)

    return tuple(flags_copy.get_list())

  def get_label_from_flags(self) -> str:
    return convert_flags_to_label(*self.flags, *self.js_flags)

  def start(self, run):
    runner = run.runner
    assert self.platform.is_macos, (
        f"Sorry, f{self.__class__} is only supported on MacOS for now")
    assert not self._is_running
    assert self._stdout_log_file is None
    if self.log_file:
      self._stdout_log_file = self.stdout_log_file.open("w")
    self._pid = runner.popen(
        self.path, *self._get_browser_flags(run), stdout=self._stdout_log_file)
    runner.wait(0.5)
    self.exec_apple_script(f"""
tell application '{self.app_name}'
    activate
    set the bounds of the first window to {{50,50,1050,1050}}
end tell
    """)
    self._is_running = True

  def quit(self, runner):
    super().quit(runner)
    if self._stdout_log_file:
      self._stdout_log_file.close()
      self._stdout_log_file = None

  def show_url(self, runner, url):
    self.exec_apple_script(f"""
tell application '{self.app_name}'
    activate
    set URL of active tab of front window to '{url}'
end tell
    """)


class ChromeWebDriver(WebdriverMixin, Chrome):

  def __init__(self,
               label: str,
               path: pathlib.Path,
               js_flags: FlagsInitialDataType = None,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               driver_path: Optional[pathlib.Path] = None,
               platform: Optional[helper.Platform] = None):
    super().__init__(label, path, js_flags, flags, cache_dir, platform)
    self._driver_path = driver_path

  def _find_driver(self) -> pathlib.Path:
    finder = ChromeDriverFinder(self)
    if self.major_version == 0 or (self.path.parent / "args.gn").exists():
      return finder.find_local_build()
    return finder.download()

  def _start_driver(self, run: cb.runner.Run, driver_path: pathlib.Path):
    assert not self._is_running
    assert self.log_file
    options = ChromeOptions()
    options.set_capability("browserVersion", str(self.major_version))
    args = self._get_browser_flags(run)
    for arg in args:
      options.add_argument(arg)
    options.binary_location = str(self.path)
    logging.info("STARTING BROWSER: %s", self.path)
    logging.info("STARTING BROWSER: driver: %s", driver_path)
    logging.info("STARTING BROWSER: args: %s", shlex.join(args))
    # pytype: disable=wrong-keyword-args
    service = ChromeService(
        executable_path=str(driver_path),
        log_path=self.driver_log_file,
        service_args=[])
    service.log_file = self.stdout_log_file.open("w")
    driver = webdriver.Chrome(options=options, service=service)
    # pytype: enable=wrong-keyword-args
    # Prevent debugging overhead.
    driver.execute_cdp_cmd("Runtime.setMaxCallStackSizeToCapture", {"size": 0})
    return driver

  def _check_driver_version(self):
    # TODO
    # version = self.platform.sh_stdout(self._driver_path, "--version")
    pass


class ChromeDriverFinder:
  URL: Final[str] = "http://chromedriver.storage.googleapis.com"
  OMAHA_PROXY_URL: Final[str] = "https://omahaproxy.appspot.com/deps.json"
  CHROMIUM_LISTING_URL: Final[str] = (
      "https://www.googleapis.com/storage/v1/b/chromium-browser-snapshots/o/")

  driver_path: pathlib.Path

  def __init__(self, browser: ChromeWebDriver):
    self.browser = browser
    self.platform = browser.platform
    assert self.browser.is_local, (
        "Cannot download chromedriver for remote browser yet")

  def find_local_build(self) -> pathlib.Path:
    # assume it's a local build
    self.driver_path = self.browser.path.parent / "chromedriver"
    if not self.driver_path.exists():
      raise Exception(f"Driver '{self.driver_path}' does not exist. "
                      "Please build 'chromedriver' manually for local builds.")
    return self.driver_path

  def download(self) -> pathlib.Path:
    extension = ""
    if self.platform.is_win:
      extension = ".exe"
    self.driver_path = (
        BROWSERS_CACHE /
        f"chromedriver-{self.browser.major_version}{extension}")
    if not self.driver_path.exists():
      self._find_driver_download()
    return self.driver_path

  def _find_driver_download(self):
    major_version = self.browser.major_version
    logging.info("CHROMEDRIVER Downloading from %s for %s v%s", self.URL,
                 self.browser.type, major_version)
    driver_version = None
    listing_url = None
    if major_version <= 69:
      with helper.urlopen(f"{self.URL}/2.46/notes.txt") as response:
        lines = response.read().decode("utf-8").split("\n")
        for i, line in enumerate(lines):
          if not line.startswith("---"):
            continue
          [min, max] = map(int, re.findall(r"\d+", lines[i + 1]))
          if min <= major_version and major_version <= max:
            match = re.search(r"\d\.\d+", line)
            assert match, "Could not parse version number"
            driver_version = match.group(0)
            break
    else:
      url = f"{self.URL}/LATEST_RELEASE_{major_version}"
      try:
        with helper.urlopen(url) as response:
          driver_version = response.read().decode("utf-8")
        listing_url = f"{self.URL}/index.html?path={driver_version}/"
      except urllib.error.HTTPError as e:
        if e.code != 404:
          raise
    if driver_version is not None:
      if self.platform.is_linux:
        arch_suffix = "linux64"
      elif self.platform.is_macos:
        arch_suffix = "mac64"
        if self.platform.is_arm64:
          # The uploaded chromedriver archives changed the naming scheme after
          # chrome version 106.0.5249.21 for Arm64 (previously m1):
          #   before: chromedriver_mac64_m1.zip
          #   after:  chromedriver_mac_arm64.zip
          LAST_OLD_NAMING_VERSION = (106, 0, 5249, 21)
          version_tuple = tuple(map(int, driver_version.split(".")))
          if version_tuple <= LAST_OLD_NAMING_VERSION:
            arch_suffix = "mac64_m1"
          else:
            arch_suffix = "mac_arm64"
      elif self.platform.is_win:
        arch_suffix = "win32"
      else:
        raise NotImplementedError("Unsupported chromedriver platform")
      url = (f"{self.URL}/{driver_version}/" f"chromedriver_{arch_suffix}.zip")
    else:
      # Try downloading the canary version
      # Lookup the branch name
      url = f"{self.OMAHA_PROXY_URL}?version={self.browser.version}"
      with helper.urlopen(url) as response:
        version_info = json.loads(response.read().decode("utf-8"))
        assert version_info["chromium_version"] == self.browser.version
        chromium_base_position = int(version_info["chromium_base_position"])
      # Use prefixes to limit listing results and increase changes of finding
      # a matching version
      arch_suffix = "Linux"
      if self.platform.is_macos:
        arch_suffix = "Mac"
        if self.platform.is_arm64:
          arch_suffix = "Mac_Arm"
      elif self.platform.is_win:
        arch_suffix = "Win"
      base_prefix = str(chromium_base_position)[:4]
      listing_url = (
          self.CHROMIUM_LISTING_URL +
          f"?prefix={arch_suffix}/{base_prefix}&maxResults=10000")
      with helper.urlopen(listing_url) as response:
        listing = json.loads(response.read().decode("utf-8"))

      versions = []
      for version in listing["items"]:
        if "name" not in version:
          continue
        if "mediaLink" not in version:
          continue
        name = version["name"]
        if "chromedriver" not in name:
          continue
        parts = name.split("/")
        if len(parts) != 3:
          continue
        arch, base, file = parts
        versions.append((int(base), version["mediaLink"]))
      versions.sort()

      url = None
      for i in range(len(versions)):
        base, url = versions[i]
        if base > chromium_base_position:
          base, url = versions[i - 1]
          break

      assert url is not None, (
          "Please manually compile/download chromedriver for "
          f"{self.browser.type} {self.browser.version}")

    logging.info("CHROMEDRIVER Downloading for version "
                 f"{major_version}: {listing_url or url}")
    with tempfile.TemporaryDirectory() as tmp_dir:
      zip_file = pathlib.Path(tmp_dir) / "download.zip"
      self.platform.download_to(url, zip_file)
      with zipfile.ZipFile(zip_file, "r") as zip_ref:
        zip_ref.extractall(zip_file.parent)
      zip_file.unlink()
      maybe_driver = None
      maybe_drivers: List[pathlib.Path] = [
          path for path in zip_file.parent.glob("**/*")
          if path.is_file() and "chromedriver" in path.name
      ]
      if len(maybe_drivers) > 0:
        maybe_driver = maybe_drivers[0]
      assert maybe_driver and maybe_driver.is_file(), (
          f"Extracted driver at {maybe_driver} does not exist.")
      BROWSERS_CACHE.mkdir(parents=True, exist_ok=True)
      maybe_driver.rename(self.driver_path)
      self.driver_path.chmod(self.driver_path.stat().st_mode | stat.S_IEXEC)
