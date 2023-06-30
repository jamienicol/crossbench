# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import json
import logging
import pathlib
import re
import shlex
import stat
import tempfile
import urllib.error
import zipfile
from typing import (TYPE_CHECKING, Dict, Final, List, Optional, Sequence, Tuple,
                    Type, cast)

from selenium.webdriver.chromium.options import ChromiumOptions
from selenium.webdriver.chromium.service import ChromiumService
from selenium.webdriver.chromium.webdriver import ChromiumDriver

from crossbench import exception, helper
from crossbench.browsers.browser import BROWSERS_CACHE
from crossbench.browsers.webdriver import WebDriverBrowser
from crossbench.flags import ChromeFlags, Flags
from crossbench.platform.android_adb import AndroidAdbPlatform

from .chromium import Chromium

if TYPE_CHECKING:
  from crossbench.browsers.splash_screen import SplashScreen
  from crossbench.browsers.viewport import Viewport
  from crossbench.platform import Platform
  from crossbench.runner import Run


class ChromiumWebDriver(WebDriverBrowser, Chromium, metaclass=abc.ABCMeta):

  WEB_DRIVER_OPTIONS: Type[ChromiumOptions] = ChromiumOptions
  WEB_DRIVER_SERVICE: Type[ChromiumService] = ChromiumService

  def __init__(
      self,
      label: str,
      path: Optional[pathlib.Path] = None,
      flags: Optional[Flags.InitialDataType] = None,
      js_flags: Optional[Flags.InitialDataType] = None,
      cache_dir: Optional[pathlib.Path] = None,
      type: str = "chromium",  # pylint: disable=redefined-builtin
      driver_path: Optional[pathlib.Path] = None,
      viewport: Optional[Viewport] = None,
      splash_screen: Optional[SplashScreen] = None,
      platform: Optional[Platform] = None):
    super().__init__(label, path, flags, js_flags, cache_dir, type, driver_path,
                     viewport, splash_screen, platform)

  def _use_local_chromedriver(self) -> bool:
    return self.major_version == 0 or (self.app_path.parent /
                                       "args.gn").exists()

  def _find_driver(self) -> pathlib.Path:
    if self._driver_path:
      return self._driver_path
    finder = ChromeDriverFinder(self)
    assert self.app_path
    if self._use_local_chromedriver():
      return finder.find_local_build()
    try:
      return finder.download()
    except DriverNotFoundError as original_download_error:
      logging.debug(
          "Could not download chromedriver, "
          "falling back to finding local build: %s", original_download_error)
      try:
        return finder.find_local_build()
      except DriverNotFoundError as e:
        logging.debug("Could not find fallback chromedriver: %s", e)
        raise original_download_error from e
      # to make an old pytype version happy
      return pathlib.Path()

  def _start_driver(self, run: Run,
                    driver_path: pathlib.Path) -> ChromiumDriver:
    assert not self._is_running
    assert self.log_file
    args = self._get_browser_flags_for_run(run)
    options = self._create_options(args)
    logging.info("STARTING BROWSER: %s", self.path)
    logging.info("STARTING BROWSER: driver: %s", driver_path)
    logging.info("STARTING BROWSER: args: %s", shlex.join(args))
    # pytype: disable=wrong-keyword-args
    service = self.WEB_DRIVER_SERVICE(
        executable_path=str(driver_path),
        log_path=str(self.driver_log_file),
        # TODO: support clean logging of chrome stdout / stderr
        service_args=["--verbose"])
    service.log_file = self.stdout_log_file.open("w", encoding="utf-8")
    driver = self._create_driver(options, service)
    # pytype: enable=wrong-keyword-args
    # Prevent debugging overhead.
    driver.execute_cdp_cmd("Runtime.setMaxCallStackSizeToCapture", {"size": 0})
    return driver

  def _create_options(self, args: Sequence[str]) -> ChromiumOptions:
    assert not self._is_running
    options: ChromiumOptions = self.WEB_DRIVER_OPTIONS()
    options.set_capability("browserVersion", str(self.major_version))
    # Don't wait for document-ready.
    options.set_capability("pageLoadStrategy", "eager")
    for arg in args:
      options.add_argument(arg)
    options.binary_location = str(self.path)
    return options

  @abc.abstractmethod
  def _create_driver(self, options: ChromiumOptions,
                     service: ChromiumService) -> ChromiumDriver:
    pass

  def _check_driver_version(self) -> None:
    # TODO
    # version = self.platform.sh_stdout(self._driver_path, "--version")
    pass


class ChromiumWebDriverAndroid(ChromiumWebDriver):

  @property
  def platform(self) -> AndroidAdbPlatform:
    assert isinstance(
        self._platform,
        AndroidAdbPlatform), (f"Invalid platform: {self._platform}")
    return cast(AndroidAdbPlatform, self._platform)

  def _resolve_binary(self, path: pathlib.Path) -> pathlib.Path:
    return path

  # TODO: implement setting a clean profile on android
  _UNSUPPORTED_FLAGS = (
      "--user-data-dir",
      "--disable-sync",
      "--window-size",
      "--window-position",
  )

  def _filter_flags_for_run(self, flags: Flags) -> Flags:
    assert isinstance(flags, ChromeFlags)
    chrome_flags = cast(ChromeFlags, flags)
    for flag in self._UNSUPPORTED_FLAGS:
      if flag not in chrome_flags:
        continue
      flag_value = chrome_flags.pop(flag, None)
      logging.debug("Chrome Android: Removed unsupported flag: %s=%s", flag,
                    flag_value)
    return chrome_flags

  def _create_options(self, args: Sequence[str]) -> ChromiumOptions:
    options: ChromiumOptions = super()._create_options(args)
    options.binary_location = ""
    package = self.platform.app_path_to_package(self.path)
    options.add_experimental_option("androidPackage", package)
    options.add_experimental_option("androidDeviceSerial",
                                    self.platform.adb.serial_id)
    return options


class DriverNotFoundError(ValueError):
  pass


class ChromeDriverFinder:
  URL: Final[str] = "http://chromedriver.storage.googleapis.com"
  CHROMIUM_LISTING_URL: Final[str] = (
      "https://www.googleapis.com/storage/v1/b/chromium-browser-snapshots/o/")
  CHROMIUM_DASH_URL: Final[str] = (
      "https://chromiumdash.appspot.com/fetch_releases")

  driver_path: pathlib.Path

  def __init__(self, browser: ChromiumWebDriver):
    self.browser = browser
    self.platform = browser.platform
    self.host_platform = browser.platform.host_platform
    assert self.browser.is_local, (
        "Cannot download chromedriver for remote browser yet")
    extension = ""
    if self.host_platform.is_win:
      extension = ".exe"
    self.driver_path = (
        BROWSERS_CACHE /
        f"chromedriver-{self.browser.major_version}{extension}")

  def find_local_build(self) -> pathlib.Path:
    assert self.browser.app_path
    # assume it's a local build
    self.driver_path = self.browser.app_path.parent / "chromedriver"
    if not self.driver_path.exists():
      raise DriverNotFoundError(
          f"Driver '{self.driver_path}' does not exist. "
          "Please build 'chromedriver' manually for local builds.")
    return self.driver_path

  def download(self) -> pathlib.Path:
    if not self.driver_path.exists():
      with exception.annotate(
          f"Downloading chromedriver for {self.browser.version}"):
        self._download()

    return self.driver_path

  def _download(self) -> None:
    major_version = self.browser.major_version
    logging.info("CHROMEDRIVER Downloading from %s for %s v%s", self.URL,
                 self.browser.type, major_version)
    listing_url, url = self._find_stable_url(major_version)
    if not url:
      url = self._find_canary_url()

    if not url:
      raise DriverNotFoundError(
          "Please manually compile/download chromedriver for "
          f"{self.browser.type} {self.browser.version}")

    logging.info("CHROMEDRIVER Downloading for version %s: %s", major_version,
                 listing_url or url)
    with tempfile.TemporaryDirectory() as tmp_dir:
      if ".zip" not in url:
        maybe_driver = pathlib.Path(tmp_dir) / "chromedriver"
        self.host_platform.download_to(url, maybe_driver)
      else:
        zip_file = pathlib.Path(tmp_dir) / "download.zip"
        self.host_platform.download_to(url, zip_file)
        with zipfile.ZipFile(zip_file, "r") as zip_ref:
          zip_ref.extractall(zip_file.parent)
        zip_file.unlink()
        maybe_driver = None
        candidates: List[pathlib.Path] = [
            path for path in zip_file.parent.glob("**/*")
            if path.is_file() and "chromedriver" in path.name
        ]
        # Find exact match first:
        maybe_drivers: List[pathlib.Path] = [
            path for path in candidates if path.stem == "chromedriver"
        ]
        # Backup less strict matching:
        maybe_drivers += candidates
        if len(maybe_drivers) > 0:
          maybe_driver = maybe_drivers[0]
      if not maybe_driver or not maybe_driver.is_file():
        raise DriverNotFoundError(
            f"Extracted driver at {maybe_driver} does not exist.")
      BROWSERS_CACHE.mkdir(parents=True, exist_ok=True)
      maybe_driver.rename(self.driver_path)
      self.driver_path.chmod(self.driver_path.stat().st_mode | stat.S_IEXEC)

  def _find_stable_url(
      self, major_version: int) -> Tuple[Optional[str], Optional[str]]:
    driver_version: Optional[str] = None
    listing_url: Optional[str] = None
    if major_version <= 69:
      with helper.urlopen(f"{self.URL}/2.46/notes.txt") as response:
        lines = response.read().decode("utf-8").split("\n")
        for i, line in enumerate(lines):
          if not line.startswith("---"):
            continue
          [min_version, max_version] = map(int,
                                           re.findall(r"\d+", lines[i + 1]))
          if min_version <= major_version <= max_version:
            match = re.search(r"\d\.\d+", line)
            if not match:
              raise DriverNotFoundError(
                  f"Could not parse version number: {line}")
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
          raise DriverNotFoundError(f"Could not query {url}") from e
    if not driver_version:
      return listing_url, None

    if self.host_platform.is_linux:
      arch_suffix = "linux64"
    elif self.host_platform.is_macos:
      arch_suffix = "mac64"
      if self.host_platform.is_arm64:
        # The uploaded chromedriver archives changed the naming scheme after
        # chrome version 106.0.5249.21 for Arm64 (previously m1):
        #   before: chromedriver_mac64_m1.zip
        #   after:  chromedriver_mac_arm64.zip
        last_old_naming_version = (106, 0, 5249, 21)
        version_tuple = tuple(map(int, driver_version.split(".")))
        if version_tuple <= last_old_naming_version:
          arch_suffix = "mac64_m1"
        else:
          arch_suffix = "mac_arm64"
    elif self.host_platform.is_win:
      arch_suffix = "win32"
    else:
      raise DriverNotFoundError("Unsupported chromedriver platform")
    url = f"{self.URL}/{driver_version}/" f"chromedriver_{arch_suffix}.zip"
    return listing_url, url

  CHROMIUM_DASH_PARAMS: Dict[Tuple[str, str], Dict] = {
      ("linux", "x64"): {
          "dash_platform": "linux",
          "dash_channel": "dev",
      },
      ("macos", "x64"): {
          "dash_platform": "mac",
      },
      ("macos", "arm64"): {
          "dash_platform": "mac",
      },
      ("win", "ia32"): {
          "dash_platform": "win",
      },
      ("win", "x64"): {
          "dash_platform": "win64",
      },
  }

  CHROMIUM_LISTING_PREFIX: Dict[Tuple[str, str], str] = {
      ("linux", "x64"): "Linux_x64",
      ("macos", "x64"): "Mac",
      ("macos", "arm64"): "Mac_Arm",
      ("win", "ia32"): "Win",
      ("win", "x64"): "Win_x64",
  }

  def _find_canary_url(self) -> Optional[str]:
    logging.debug("Try downloading the chromedriver canary version")
    properties = self.CHROMIUM_DASH_PARAMS.get(self.host_platform.key)
    if not properties:
      raise DriverNotFoundError(
          f"Unsupported platform={self.platform}, key={self.host_platform.key}")
    dash_platform = properties["dash_platform"]
    dash_channel = properties.get("dash_channel", "canary")

    url = (f"{self.CHROMIUM_DASH_URL}?"
           f"platform={dash_platform}&channel={dash_channel}")
    chromium_base_position = 0
    with helper.urlopen(url) as response:
      version_infos = list(json.loads(response.read().decode("utf-8")))
      if not version_infos:
        raise DriverNotFoundError("Could not find latest version info for "
                                  f"platform={self.host_platform}")
      for version_info in version_infos:
        if version_info["version"] == self.browser.version:
          chromium_base_position = int(
              version_info["chromium_main_branch_position"])
          break

    if not chromium_base_position and version_infos:
      # Android has a slightly different release cycle than the desktop
      # versions. Assume that the latest canary version is good enough
      first_version_info = version_infos[0]
      chromium_base_position = int(
          first_version_info["chromium_main_branch_position"])
      logging.warning(
          "Falling back to latest (not precisely matching) "
          "canary chromedriver %s", first_version_info["version"])

    if not chromium_base_position:
      raise DriverNotFoundError("Could not find matching canary chromedriver "
                                f"for {self.browser.version}")
    # Use prefixes to limit listing results and increase chances of finding
    # a matching version
    listing_prefix = self.CHROMIUM_LISTING_PREFIX.get(self.host_platform.key)
    if not listing_prefix:
      raise NotImplementedError(
          f"Unsupported chromedriver platform {self.host_platform}")
    base_prefix = str(chromium_base_position)[:4]
    listing_url = (
        self.CHROMIUM_LISTING_URL +
        f"?prefix={listing_prefix}/{base_prefix}&maxResults=10000")
    with helper.urlopen(listing_url) as response:
      listing = json.loads(response.read().decode("utf-8"))

    versions = []
    logging.debug("Filtering %s candidate URLs.", len(listing["items"]))
    for version in listing["items"]:
      if "name" not in version:
        continue
      if "mediaLink" not in version:
        continue
      name = version["name"]
      if "chromedriver" not in name:
        continue
      parts = name.split("/")
      if "chromedriver" not in parts[-1] or len(parts) < 3:
        continue
      base = parts[1]
      try:
        int(base)
      except ValueError:
        # Ignore ig base is not an int
        continue
      versions.append((int(base), version["mediaLink"]))
    versions.sort()
    logging.debug("Found candidates: %s", versions)
    logging.debug("chromium_base_position=%s", chromium_base_position)

    for i in range(len(versions)):
      base, url = versions[i]
      if base > chromium_base_position:
        base, url = versions[i - 1]
        return url
    return None
