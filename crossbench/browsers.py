# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import html
import json
import logging
import re
import shlex
import shutil
import stat
import tempfile
import time
import traceback
import urllib.request
import zipfile
import pathlib
import typing
import urllib.parse
from typing import Any, Dict, Final, List, Optional, Sequence, Set

import selenium
from selenium import webdriver
import selenium.common.exceptions
from selenium.webdriver.safari.options import Options as SafariOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

import crossbench as cb
import crossbench.runner
from crossbench import helper
import crossbench.probes.base
import crossbench.flags

# =============================================================================

FlagsInitialDataType = cb.flags.Flags.InitialDataType

BROWSERS_CACHE = pathlib.Path(__file__).parent.parent / ".browsers-cache"

# =============================================================================


class Browser(abc.ABC):

  @classmethod
  def default_flags(cls, initial_data: FlagsInitialDataType = None
                   ) -> cb.flags.Flags:
    return cb.flags.Flags(initial_data)

  def __init__(self,
               label: str,
               path: Optional[pathlib.Path],
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               type: Optional[str] = None,
               platform: Optional[helper.Platform] = None):
    self.platform = platform or helper.platform
    # Marked optional to make subclass constructor calls easier with pytype.
    assert type
    self.type: str = type
    self.label: str = label
    self.path: Optional[pathlib.Path] = path
    if path:
      self.path = self._resolve_binary(path)
      self.version: str = self._extract_version()
      self.major_version: int = int(self.version.split(".")[0])
      short_name = f"{self.type}_v{self.major_version}_{self.label}".lower()
    else:
      short_name = f"{self.type}_{self.label}".lower()
    self.short_name: str = short_name.replace(" ", "_")
    self.width: int = 1500
    self.height: int = 1000
    self.x: int = 10
    # Move down to avoid menu bars
    self.y: int = 50
    self._is_running: bool = False
    self.cache_dir: Optional[pathlib.Path] = cache_dir
    self.clear_cache_dir: bool = True
    self._pid = None
    self._probes: Set[cb.probes.Probe] = set()
    self._flags: cb.flags.Flags = self.default_flags(flags)

  @property
  def is_headless(self) -> bool:
    return False

  @property
  def flags(self) -> cb.flags.Flags:
    return self._flags

  @property
  def pid(self):
    return self._pid

  @property
  def is_local(self) -> bool:
    return True

  def _resolve_binary(self, path: pathlib.Path) -> pathlib.Path:
    assert path.exists(), f"Binary at path={path} does not exist."
    self.app_path = path
    self.app_name: str = self.app_path.stem
    if self.platform.is_macos:
      path = self._resolve_macos_binary(path)
    assert path.is_file(), (f"Binary at path={path} is not a file.")
    return path

  def _resolve_macos_binary(self, path: pathlib.Path) -> pathlib.Path:
    assert self.platform.is_macos
    candidate = self.platform.search_binary(path)
    if not candidate or not candidate.is_file():
      raise ValueError(f"Could not find browser executable in {path}")
    return candidate

  def attach_probe(self, probe: cb.probes.Probe):
    self._probes.add(probe)
    probe.attach(self)

  def details_json(self) -> Dict[str, Any]:
    return {
        "label": self.label,
        "browser": self.type,
        "short_name": self.short_name,
        "app_name": self.app_name,
        "version": self.version,
        "flags": tuple(self.flags.get_list()),
        "js_flags": tuple(),
        "path": str(self.path),
        "clear_cache_dir": self.clear_cache_dir,
        "major_version": self.major_version,
        "log": {}
    }

  def setup_binary(self, runner: cb.runner.Runner):
    pass

  def setup(self, run: cb.runner.Run):
    assert not self._is_running
    runner = run.runner
    self.clear_cache(runner)
    self.start(run)
    assert self._is_running
    self._prepare_temperature(run)
    self.show_url(runner, self.info_data_url(run))
    runner.wait(runner.default_wait)

  @abc.abstractmethod
  def _extract_version(self) -> str:
    pass

  def set_log_file(self, path: pathlib.Path):
    pass

  def clear_cache(self, runner: cb.runner.Runner):
    if self.clear_cache_dir and self.cache_dir and self.cache_dir.exists():
      shutil.rmtree(self.cache_dir)

  @abc.abstractmethod
  def start(self, run: cb.runner.Run):
    pass

  def _prepare_temperature(self, run: cb.runner.Run):
    """Warms up the browser by loading the page 3 times."""
    runner = run.runner
    if run.temperature != "cold" and run.temperature:
      for _ in range(3):
        # TODO(cbruni): add no_collect argument
        run.story.run(run)
        runner.wait(run.story.duration / 2)
        self.show_url(runner, "about:blank")
        runner.wait(runner.default_wait)

  def info_data_url(self, run):
    page = ("<html><head>"
            "<title>Browser Details</title>"
            "<style>"
            """
            html { font-family: sans-serif; }
            dl {
              display: grid;
              grid-template-columns: max-content auto;
            }
            dt { grid-column-start: 1; }
            dd { grid-column-start: 2;  font-family: monospace; }
            """
            "</style>"
            "<head><body>"
            f"<h1>{html.escape(self.type)} {html.escape(self.version)}</h2>"
            "<dl>")
    for property_name, value in self.details_json().items():
      page += f"<dt>{html.escape(property_name)}</dt>"
      page += f"<dd>{html.escape(str(value))}</dd>"
    page += "</dl></body></html>"
    data_url = f"data:text/html;charset=utf-8,{urllib.parse.quote(page)}"
    return data_url

  def quit(self, runner: cb.runner.Runner):
    assert self._is_running
    try:
      self.force_quit()
    finally:
      self._pid = None

  def force_quit(self):
    logging.info("QUIT")
    if self.platform.is_macos:
      self.platform.exec_apple_script(f"""
  tell application '{self.app_name}'
    quit
  end tell
      """)
    elif self._pid:
      self.platform.terminate(self._pid)
    self._is_running = False

  @abc.abstractmethod
  def js(self,
         runner: cb.runner.Runner,
         script: str,
         timeout: Optional[float] = None,
         arguments: Sequence[object] = ()):
    pass

  @abc.abstractmethod
  def show_url(self, runner: cb.runner.Runner, url):
    pass


_FLAG_TO_PATH_RE = re.compile(r"[-/\\:\.]")


def convert_flags_to_label(*flags, index: Optional[int] = None) -> str:
  label = "default"
  if flags:
    label = _FLAG_TO_PATH_RE.sub("_", "_".join(flags).replace("--", ""))
  if index is None:
    return label
  return f"{str(index).rjust(2,'0')}_{label}"


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
    self.log_file: Optional[pathlib.Path] = None
    self._stdout_log_file = None

  def _extract_version(self):
    version_string = self.platform.app_version(self.path)
    # Sample output: "Google Chrome 90.0.4430.212 dev" => "90.0.4430.212"
    return re.findall(r"[\d\.]+", version_string)[0]

  def set_log_file(self, path):
    self.log_file = path

  @property
  def is_headless(self) -> bool:
    return "--headless" in self._flags

  @property
  def chrome_log_file(self) -> pathlib.Path:
    assert self.log_file
    return self.log_file.with_suffix(".chrome.log")

  @property
  def stdout_log_file(self) -> pathlib.Path:
    assert self.log_file
    return self.log_file.with_suffix(".stdout.log")

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

  def _get_chrome_args(self, run) -> typing.Tuple[str, ...]:
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
        self.bin_path,
        *self._get_chrome_args(run),
        stdout=self._stdout_log_file)
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


class WebdriverMixin(Browser):
  _driver: webdriver.Remote
  _driver_path: Optional[pathlib.Path]
  _driver_pid: int
  log_file: Optional[pathlib.Path]

  @property
  def driver_log_file(self) -> pathlib.Path:
    assert self.log_file
    return self.log_file.with_suffix(".driver.log")  # pytype: disable=attribute-error

  def setup_binary(self, runner: cb.runner.Runner):
    self._driver_path = self._find_driver()
    assert self._driver_path.exists(), (
        f"Webdriver path '{self._driver_path}' does not exist")

  @abc.abstractmethod
  def _find_driver(self) -> pathlib.Path:
    pass

  @abc.abstractmethod
  def _check_driver_version(self):
    pass

  def start(self, run: cb.runner.Run):
    assert not self._is_running
    assert self._driver_path
    self._check_driver_version()
    self._driver = self._start_driver(run, self._driver_path)
    if hasattr(self._driver, "service"):
      self._driver_pid = self._driver.service.process.pid
      for child in self.platform.process_children(self._driver_pid):
        if str(child["exe"]) == str(self.path):
          self._pid = int(child["pid"])
          break
    self._is_running = True
    # Force main window to foreground.
    self._driver.switch_to.window(self._driver.current_window_handle)
    self._driver.set_window_position(self.x, self.y)
    self._driver.set_window_size(self.width, self.height)
    self._check_driver_version()
    self.show_url(run.runner, self.info_data_url(run))

  @abc.abstractmethod
  def _start_driver(self, run: cb.runner.Run,
                    driver_path: pathlib.Path) -> webdriver.Remote:
    pass

  def details_json(self) -> Dict[str, Any]:
    details: Dict[str, Any] = super().details_json()  # pytype: disable=attribute-error
    details["log"]["driver"] = str(self.driver_log_file)
    return details

  def show_url(self, runner: cb.runner.Runner, url):
    logging.debug("SHOW_URL %s", url)
    assert self._driver.window_handles, "Browser has no more opened windows."
    self._driver.switch_to.window(self._driver.window_handles[0])
    try:
      self._driver.get(url)
    except selenium.common.exceptions.WebDriverException as e:
      if e.msg and "net::ERR_CONNECTION_REFUSED" in e.msg:
        raise Exception(f"Browser failed to load URL={url}. "
                        "The URL is likely unreachable.")
      raise

  def js(self,
         runner: cb.runner.Runner,
         script: str,
         timeout: Optional[float] = None,
         arguments: Sequence[object] = ()):
    logging.debug("RUN SCRIPT timeout=%s, script: %s", timeout, script[:100])
    assert self._is_running
    try:
      if timeout is not None:
        assert timeout > 0, f"timeout must be a positive number, got: {timeout}"
        self._driver.set_script_timeout(timeout)
      return self._driver.execute_script(script, *arguments)
    except selenium.common.exceptions.WebDriverException as e:
      raise Exception(f"Could not execute JS: {e.msg}")

  def quit(self, runner: cb.runner.Runner):
    assert self._is_running
    self.force_quit()

  def force_quit(self):
    if getattr(self, "_driver", None) is None:
      return
    logging.debug("QUIT")
    try:
      try:
        # Close the current window.
        self._driver.close()
        time.sleep(0.1)
      except selenium.common.exceptions.NoSuchWindowException:
        # No window is good.
        pass
      try:
        self._driver.quit()
      except selenium.common.exceptions.InvalidSessionIdException:
        return True
      # Sometimes a second quit is needed, ignore any warnings there
      try:
        self._driver.quit()
      except Exception:
        pass
      return True
    except Exception:
      logging.debug(traceback.format_exc())
    finally:
      self._is_running = False
    return False


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
    stdout_log_file = self.log_file.with_suffix(".stdout.log")
    options = ChromeOptions()
    options.set_capability("browserVersion", str(self.major_version))
    args = self._get_chrome_args(run)
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
    service.log_file = stdout_log_file.open("w")
    driver = webdriver.Chrome(options=options, service=service)
    # pytype: enable=wrong-keyword-args
    # Prevent debugging overhead.
    driver.execute_cdp_cmd("Runtime.setMaxCallStackSizeToCapture", {"size": 0})
    return driver

  def _check_driver_version(self):
    # TODO
    # version = self.platform.sh_stdout(self._driver_path, "--version")
    pass



class Safari(Browser):

  @classmethod
  def default_path(cls):
    return pathlib.Path("/Applications/Safari.app")

  @classmethod
  def technology_preview_path(cls):
    return pathlib.Path("/Applications/Safari Technology Preview.app")

  def __init__(self,
               label: str,
               path: pathlib.Path,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               platform: Optional[helper.MacOSPlatform] = None):
    super().__init__(label, path, flags, type="safari", platform=platform)
    assert self.platform.is_macos, "Safari only works on MacOS"
    self.bundle_name = self.path.stem.replace(" ", "")
    assert cache_dir is None, "Cannot set custom cache dir for Safari"
    self.cache_dir = pathlib.Path(
        f"~/Library/Containers/com.apple.{self.bundle_name}/Data/Library/Caches"
    ).expanduser()

  def _extract_version(self) -> str:
    app_path = self.path.parents[2]
    return self.platform.app_version(app_path)

  def start(self, run: cb.runner.Run):
    assert self.platform.is_macos
    assert not self._is_running
    self.platform.exec_apple_script(f"""
tell application '{self.app_name}'
  activate
end tell
    """)
    self.platform.sleep(1)
    self.platform.exec_apple_script(f"""
tell application '{self.app_name}'
  tell application "System Events"
      to click menu item "New Private Window"
      of menu "File" of menu bar 1
      of process '{self.bundle_name}'
  set URL of current tab of front window to ''
  set the bounds of the first window
      to {{{self.x},{self.y},{self.width},{self.height}}}
  tell application "System Events"
      to keystroke "e" using {{command down, option down}}
  tell application "System Events"
      to click menu item 1 of menu 2 of menu bar 1
      of process '{self.bundle_name}'
  tell application "System Events"
      to set position of window 1
      of process '{self.bundle_name}' to {400, 400}
end tell
    """)
    self.platform.sleep(2)
    self._is_running = True

  def show_url(self, runner: cb.runner.Runner, url):
    self.platform.exec_apple_script(f"""
tell application '{self.app_name}'
    activate
    set URL of current tab of front window to '{url}'
end tell
    """)


class SafariWebDriver(WebdriverMixin, Safari):

  def __init__(self,
               label: str,
               path: pathlib.Path,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[pathlib.Path] = None,
               platform: Optional[helper.MacOSPlatform] = None):
    super().__init__(label, path, flags, cache_dir, platform)

  def _find_driver(self) -> pathlib.Path:
    driver_path = self.path.parent / "safaridriver"
    if not driver_path.exists():
      # The system-default Safari version doesn't come with the driver
      driver_path = pathlib.Path("/usr/bin/safaridriver")
    return driver_path

  def _start_driver(self, run: cb.runner.Run, driver_path: pathlib.Path):
    assert not self._is_running
    logging.info("STARTING BROWSER: browser: %s driver: %s", self.path,
                 driver_path)
    options = SafariOptions()
    options.binary_location = str(self.path)
    capabilities = DesiredCapabilities.SAFARI.copy()
    capabilities["safari.cleanSession"] = "true"
    # Enable browser logging
    capabilities["safari:diagnose"] = "true"
    if "Technology Preview" in self.app_name:
      capabilities["browserName"] = "Safari Technology Preview"
    driver = webdriver.Safari(  # pytype: disable=wrong-keyword-args
        executable_path=str(driver_path),
        desired_capabilities=capabilities,
        options=options)
    assert driver.session_id, "Could not start webdriver"
    logs = (
        pathlib.Path("~/Library/Logs/com.apple.WebDriver/").expanduser() /
        driver.session_id)
    self.log_file = list(logs.glob("safaridriver*"))[0]
    assert self.log_file.is_file()
    return driver

  def _check_driver_version(self):
    # The bundled driver is always ok
    for parent in self._driver_path.parents:
      if parent == self.path.parent:
        return True
    version = self.platform.sh_stdout(self._driver_path, "--version")
    assert str(self.major_version) in version, (
        f"safaridriver={self._driver_path} version='{version}' "
        f" doesn't match safari version={self.major_version}")

  def clear_cache(self, runner: cb.runner.Runner):
    pass

  def quit(self, runner: cb.runner.Runner):
    super().quit(runner)
    # Safari needs some additional push to quit properly
    self.platform.exec_apple_script(f"""
  tell application '{self.app_name}'
    quit
  end tell
      """)


class RemoteWebDriver(WebdriverMixin, Browser):
  """Represent a remote WebDriver that has already been started"""

  def __init__(self,
               label: str,
               driver: webdriver.Remote):
    super().__init__(label=label, path=None, type="remote")
    self._driver = driver

  def _check_driver_version(self):
    raise NotImplementedError()

  def _extract_version(self):
    raise NotImplementedError()

  def _find_driver(self) -> pathlib.Path:
    raise NotImplementedError()

  def _start_driver(self, run: cb.runner.Run, driver_path: pathlib.Path):
    raise NotImplementedError()

  def setup_binary(self, runner: cb.runner.Runner):
    pass

  def start(self, run: cb.runner.Run):
    # Driver has already been started. We just need to mark it as running.
    self._is_running = True
    self._driver.set_window_position(self.x, self.y)
    self._driver.set_window_size(self.width, self.height)

  def quit(self, runner: cb.runner.Runner):
    # External code that started the driver is responsible for shutting it down.
    self._is_running = False

  def details_json(self) -> Dict[str, Any]:
    return {
        "label": self.label,
        "app_name": "remote webdriver",
        "flags": (),
        "js_flags": (),
        "log": {},
    }
