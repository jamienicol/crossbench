# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import InvalidSessionIdException
from selenium import webdriver
import selenium
import json
import logging
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile
import traceback
import urllib.request
import zipfile
from typing import Iterable, Optional, Dict, List

import psutil

from crossbench import helper, probes, flags, runner

# =============================================================================

FlagsInitialDataType = flags.Flags.InitialDataType

BROWSERS_CACHE = Path(__file__).parent.parent / '.browsers-cache'

# =============================================================================


class Browser:
  @classmethod
  def default_flags(cls, initial_data:FlagsInitialDataType=None):
    return flags.Flags(initial_data)

  def __init__(self,
               label: str,
               path: Path,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[Path] = None,
               type : Optional[str] = None):
    # Marked optional to make subclass constructor calls easier with pytype.
    assert type
    self.type = type
    self.label = label
    self.path = path
    assert self.path.exists(), f'Binary at path={self.path} does not exist.'
    if helper.platform.is_macos:
      self._resolve_macos_binary()
    assert self.path.is_file(), (
        f'Binary at bin_path={self.bin_path} is not a file.')
    self.app_name = path.stem
    self.version = self._extract_version()
    self.version_number = int(self.version.split(".")[0])
    self.short_name = f'{self.label}_{self.type}_v{self.version_number}'\
        .lower().replace(' ', '_')
    self.width = 1500
    self.height = 1000
    self.x = 10
    # Move down to avoid menu bars
    self.y = 50
    self.is_running = False
    self.browser_process = None
    self.cache_dir = cache_dir
    self.clear_cache_dir = True
    self._pid = None
    self._probes = set()
    self._flags = self.default_flags(flags)

  @property
  def is_headless(self):
    return False

  @property
  def flags(self):
    return self._flags

  @property
  def pid(self):
    return self._pid

  @property
  def all_pids(self):
    pid = self.pid
    pids = set([pid])
    current_process = psutil.Process(pid)
    for child in current_process.children(recursive=True):
      pids.add(child.pid)
    return pids

  def _resolve_macos_binary(self):
    assert self.path.is_dir(
    ), f'Expected a binary, ending in .app: path={self.path}'
    mac_os_dir = self.path / "Contents" / "MacOS"
    self.path = mac_os_dir / self.path.stem
    if self.path.exists():
      return
    candidates = [
        maybe_bin for maybe_bin in mac_os_dir.glob("*")
        if self.type.lower() in maybe_bin.name.lower()
    ]
    assert len(candidates) == 1, (
        f"Expected 1 browser candidate, got {len(candidates)} candidates={candidates}"
    )
    self.path = candidates[0]

  def attach_probe(self, probe: probes.Probe):
    self._probes.add(probe)
    probe.attach(self)

  def details_json(self):
    return dict(label=self.label,
                app_name=self.app_name,
                version=self.version,
                flags=tuple(self.flags.get_list()),
                js_flags=tuple(),
                path=str(self.path),
                clear_cache_dir=self.clear_cache_dir,
                version_number=self.version_number,
                log={})

  def setup_binary(self, runner: runner.Runner):
    pass

  def setup(self, run: runner.Run):
    assert not self.is_running
    runner = run.runner
    self.clear_cache(runner)
    self.start(run)
    assert self.is_running
    self._prepare_temperature(run)

  def _extract_major_version_number(self):
    return 0

  def set_log_file(self, path):
    pass

  def clear_cache(self, runner):
    if self.clear_cache_dir:
      runner.sh('/bin/rm', '-rf', self.cache_dir)

  def start(self, run):
    pass

  def _prepare_temperature(self, run):
    runner = run.runner
    if run.temperature == 'cold':
      return
    if run.temperature is None:
      return
    for i in range(3):
      self.show_url(runner, run.page.url)
      runner.wait(run.page.duration / 2)
      self.show_url(runner, 'about://version')
      runner.wait(runner.default_wait)
    self.show_url(runner, self.default_page)
    runner.wait(runner.default_wait * 3)

  def show_page(self, runner, page):
    self.show_url(runner, page.url)

  def quit(self, runner):
    self._pid = None
    assert self.is_running
    logging.info('QUIT')
    if helper.platform.is_macos:
      helper.platform.exec_apple_script(f'''
  tell application "{self.app_name}"
    quit
  end tell
      ''')
    elif self.browser_process:
      helper.platform.terminate(self.browser_process)
    self.is_running = False


_FLAG_TO_PATH_RE = re.compile(r"[-/\\:\.]")


def convert_flags_to_label(*flags, index=None):
  label = "default"
  if len(flags) != 0:
    label = _FLAG_TO_PATH_RE.sub("_", "_".join(flags).replace("--", ""))
  if index is None:
    return label
  return f"{str(index).rjust(2,'0')}_{label}"


class ChromeMeta(type):
  @property
  def default_path(cls):
    return cls.stable_path

  @property
  def stable_path(cls):
    if helper.platform.is_macos:
      return Path('/Applications/Google Chrome.app')
    if helper.platform.is_linux:
      for bin_name in ('google-chrome', 'chrome'):
        binary = helper.platform.search_binary(bin_name)
        if binary:
          return binary
      raise Exception("Could not find binary")
    raise NotImplementedError()

  @property
  def dev_path(cls):
    if helper.platform.is_macos:
      return Path('/Applications/Google Chrome Dev.app')
    raise NotImplementedError()

  @property
  def canary_path(cls):
    if helper.platform.is_macos:
      return Path('/Applications/Google Chrome Canary.app')
    raise NotImplementedError()

class Chrome(Browser, metaclass=ChromeMeta):
  @classmethod
  def combine(cls,
              binaries: Iterable[Path],
              js_flags_list: Optional[Iterable[FlagsInitialDataType]] = None,
              browser_flags_list: Optional[Iterable[FlagsInitialDataType]]= None,
              user_data_dir: Optional[Path] = None):
    if isinstance(binaries, Path):
      binaries = [binaries,]
    browsers = []
    empty_flags = tuple(tuple())
    for browser_flags in browser_flags_list or empty_flags:
      assert not isinstance(browser_flags_list, FlagsInitialDataType), (
          f"browser_flags should be a {FlagsInitialDataType}  but got: "
          f"{repr(browser_flags)}")
      for js_flags in js_flags_list or empty_flags:
        assert isinstance(js_flags, FlagsInitialDataType), (
            f"js_flags should be an {FlagsInitialDataType}, but got type={type(js_flags)}: "
            f"{repr(js_flags)}")
        for binary in binaries:
          assert isinstance(binary, Path), "Expected browser binary path"
          index = len(browsers)
          # Don't print a browser/binary index if there is only one
          label = convert_flags_to_label(*js_flags, *browser_flags, index=index)
          browser = cls(label,
                        binary,
                        js_flags=js_flags,
                        flags=browser_flags,
                        cache_dir=user_data_dir)
          browsers.append(browser)
    assert len(browsers) > 0, 'No browser variants produced'
    return browsers

  DEFAULT_FLAGS = [
      '--no-default-browser-check',
      '--disable-sync',
      '--no-experiments',
      '--enable-crossbench',
      '--disable-extensions',
      '--no-first-run',
  ]

  @classmethod
  def default_flags(cls, initial_data:FlagsInitialDataType=None):
    return flags.ChromeFlags(initial_data)

  def __init__(self,
               label: str,
               path: Path,
               js_flags: FlagsInitialDataType = None,
               flags: FlagsInitialDataType = None,
               cache_dir : Optional[Path] =None):
    super().__init__(label, path, type='chrome')
    assert not isinstance(
        js_flags, str), f"js_flags should be a list, but got: {repr(js_flags)}"
    assert not isinstance(
        flags, str), f"flags should be a list, but got: {repr(flags)}"
    self.default_page = 'about://version'
    self._flags = self.default_flags(Chrome.DEFAULT_FLAGS)
    self._flags.update(flags)
    self.js_flags.update(js_flags)
    if cache_dir is None:
      self.cache_dir = tempfile.TemporaryDirectory(prefix="chrome").name
      self.clear_cache_dir = True
    else:
      self.cache_dir = cache_dir
      self.clear_cache_dir = False
    self.log_file = None
    self._stdout_log_file = None

  def _extract_version(self):
    version_string = helper.platform.sh_stdout(self.path, '--version')
    # Sample output: "Google Chrome 90.0.4430.212 dev" => "90.0.4430.212"
    return re.findall(r'[\d\.]+', version_string)[0]

  def set_log_file(self, path):
    self.log_file = path

  @property
  def is_headless(self):
    return '--headless' in self._flags

  @property
  def chrome_log_file(self):
    return self.log_file.with_suffix(".chrome.log")

  @property
  def stdout_log_file(self):
    return self.log_file.with_suffix(".stdout.log")

  @property
  def js_flags(self):
    return self._flags.js_flags

  @property
  def features(self):
    return self._flags.features

  def exec_apple_script(self, script):
    return helper.platform.exec_apple_script(script)

  def details_json(self):
    details = super().details_json()
    if self.log_file:
      details['log']['chrome'] = str(self.chrome_log_file)
      details['log']['stdout'] = str(self.stdout_log_file)
    details['js_flags'] = tuple(self.js_flags.get_list())
    return details

  def _get_chrome_args(self, run):
    js_flags_copy = self.js_flags.copy()
    js_flags_copy.update(run.extra_js_flags)

    flags_copy = self.flags.copy()
    flags_copy.update(run.extra_flags)
    flags_copy['--window-size'] = f'{self.width},{self.height}'
    if len(js_flags_copy):
      flags_copy['--js-flags'] = str(js_flags_copy)
    if self.cache_dir and len(self.cache_dir) > 0:
      flags_copy['--user-data-dir'] = str(self.cache_dir)
    if self.clear_cache_dir:
      flags_copy.set('--incognito')
    if self.log_file:
      flags_copy.set('--enable-logging')
      flags_copy["--log-file"] = str(self.chrome_log_file)

    return tuple(flags_copy.get_list()) + (self.default_page, )

  def get_label_from_flags(self):
    return convert_flags_to_label(*self.flags, *self.js_flags)

  def start(self, run):
    runner = run.runner
    assert helper.platform.is_macos, (
        f"Sorry, f{self.__class__} is only supported on MacOS for now")
    assert not self.is_running
    assert self._stdout_log_file is None
    if self.log_file:
      self._stdout_log_file = self.stdout_log_file.open('w')
    self.browser_process = runner.popen(self.bin_path,
                                        *self._get_chrome_args(run),
                                        stdout=self._stdout_log_file)
    runner.wait(1)
    self.show_url(runner, self.default_page)
    self.exec_apple_script(f'''
tell application "{self.app_name}"
    activate
    set URL of active tab of front window to "about://version"
    set the bounds of the first window to {{50,50,1050,1050}}
end tell
    ''')
    self.is_running = True

  def quit(self, runner):
    super().quit(runner)
    if self._stdout_log_file:
      self._stdout_log_file.close()
      self._stdout_log_file = None

  def show_url(self, runner, url):
    self.exec_apple_script(f'''
tell application "{self.app_name}"
    activate
    set URL of active tab of front window to "{url}"
end tell
    ''')


class WebdriverMixin:
  driver: webdriver.Remote
  log_file: Path
  is_running: bool

  @property
  def driver_log_file(self):
    return self.log_file.with_suffix(".driver.log")

  def details_json(self):
    details = super().details_json()  # pytype: disable=attribute-error
    details['log']['driver'] = str(self.driver_log_file)
    return details

  def show_url(self, runner, url):
    logging.info(f"SHOW_URL {url}")
    self.driver.switch_to.window(self.driver.window_handles[0])
    try:
      self.driver.get(url)
    except selenium.common.exceptions.WebDriverException as e:
      if "net::ERR_CONNECTION_REFUSED" in e.msg:
        raise Exception(f"Browser failed to load URL={url}. "
                        "The URL is likely unreachable.") from e
      raise

  def js(self, runner, script, timeout=None, arguments=()):
    logging.info(f"RUN SCRIPT timeout={timeout}, script: {script[:100]}")
    assert self.is_running
    if timeout is not None:
      assert timeout > 0, f"timeout must be a positive number, got: {timeout}"
      self.driver.set_script_timeout(timeout)
      return self.driver.execute_script(script, *arguments)
    return self.driver.execute_script(script, *arguments)

  def quit(self, runner):
    assert self.is_running
    if self.driver is None:
      return
    logging.info('QUIT')
    try:
      # Close the current window
      self.driver.close()
      try:
        self.driver.quit()
      except InvalidSessionIdException:
        return True
      # Sometimes a second quit is needed, ignore any warnings there
      try:
        self.driver.quit()
      except Exception:
        pass
      return True
    except Exception:
      traceback.print_exc(file=sys.stdout)
    finally:
      self.is_running = False
    return False


class ChromeWebDriver(WebdriverMixin, Chrome):

  def __init__(self,
               label: str,
               path: Path,
               js_flags: FlagsInitialDataType = None,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[Path] = None,
               driver_path: Optional[Path] = None):
    super().__init__(label, path, js_flags, flags, cache_dir)
    self.driver = None
    self.driver_path = driver_path

  def setup_binary(self, runner):
    super().setup_binary(runner)
    if self.driver_path:
      pass
    if self.version_number == 0 or (self.path.parent / 'args.gn').exists():
      self._find_local_chromedriver_build()
    else:
      self.driver_path = BROWSERS_CACHE / f'chromedriver-{self.version_number}'
      if not self.driver_path.exists():
        self._find_driver_download()
    assert self.driver_path.exists(), (
      f"Could not find chromedriver at {self.driver_path}")

  def _find_local_chromedriver_build(self):
    # assume it's a local build
    self.driver_path = self.path.parent / 'chromedriver'
    if not self.driver_path.exists():
      raise Exception(f'Driver "{self.driver_path}" does not exist. '
                      'Please build "chromedriver" manually for local builds.')

  def _find_driver_download(self):
    base_url = 'http://chromedriver.storage.googleapis.com'
    logging.info(f"CHROMEDRIVER Downloading from {base_url} for "
                 f"{self.type} v{self.version_number}")
    driver_version = None
    listing_url = None
    if self.version_number <= 69:
      with helper.urlopen(f'{base_url}/2.46/notes.txt') as response:
        lines = response.read().decode('utf-8').split('\n')
        for i, line in enumerate(lines):
          if not line.startswith('---'):
            continue
          [min, max] = map(int, re.findall(r'\d+', lines[i + 1]))
          if min <= self.version_number and self.version_number <= max:
            match = re.search(r'\d\.\d+', line)
            assert match, "Could not parse version number"
            driver_version = match.group(0)
            break
    else:
      url = f'{base_url}/LATEST_RELEASE_{self.version_number}'
      try:
        with helper.urlopen(url) as response:
          driver_version = response.read().decode('utf-8')
        listing_url = f"{base_url}/index.html?path={driver_version}/"
      except urllib.error.HTTPError as e:
        if e.status != 404:
          raise
    if driver_version is not None:
      arch_suffix = ""
      if helper.platform.is_arm64:
        arch_suffix = "_m1"
      url = (f"{base_url}/{driver_version}/"
             f"chromedriver_{helper.platform.short_name}64{arch_suffix}.zip")
    else:
      # Try downloading the canary version
      # Lookup the branch name
      url = f"https://omahaproxy.appspot.com/deps.json?version={self.version}"
      with helper.urlopen(url) as response:
        version_info = json.loads(response.read().decode('utf-8'))
        assert version_info['chromium_version'] == self.version
        chromium_base_position = int(version_info['chromium_base_position'])
      # Use prefixes to limit listing results and increase changes of finding
      # a matching version
      arch_suffix = 'Mac'
      if helper.platform.is_arm64:
        arch_suffix = 'Mac_Arm'
      base_prefix = str(chromium_base_position)[:4]
      listing_url = ("https://www.googleapis.com"
                     "/storage/v1/b/chromium-browser-snapshots/o/"
                     f"?prefix={arch_suffix}/{base_prefix}&maxResults=10000")
      with helper.urlopen(listing_url) as response:
        listing = json.loads(response.read().decode('utf-8'))

      versions = []
      for version in listing['items']:
        if 'name' not in version:
          continue
        if 'mediaLink' not in version:
          continue
        name = version['name']
        if 'chromedriver' not in name:
          continue
        parts = name.split('/')
        if len(parts) != 3:
          continue
        arch, base, file = parts
        versions.append((int(base), version['mediaLink']))
      versions.sort()

      url = None
      for i in range(len(versions)):
        base, url = versions[i]
        if base > chromium_base_position:
          base, url = versions[i - 1]
          break

      assert url is not None, (
          "Please manually compile/download chromedriver for "
          f"{self.type} {self.version}")

    logging.info("CHROMEDRIVER Downloading for version "
                 f"{self.version_number}: {listing_url or url}")
    with tempfile.TemporaryDirectory() as tmp_dir:
      zip_file = Path(tmp_dir) / 'download.zip'
      helper.platform.download_to(url, zip_file)
      with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(zip_file.parent)
      maybe_driver = zip_file.parent / 'chromedriver'
      if not maybe_driver.is_file():
        maybe_driver = zip_file.parent / 'chromedriver_mac64' / 'chromedriver'
      assert maybe_driver.is_file(), \
          f"Extracted driver at {maybe_driver} does not exist."
      BROWSERS_CACHE.mkdir(parents=True, exist_ok=True)
      maybe_driver.rename(self.driver_path)
      self.driver_path.chmod(self.driver_path.stat().st_mode | stat.S_IEXEC)

  def start(self, run):
    runner = run.runner
    assert not self.is_running
    self.options = ChromeOptions()
    args = self._get_chrome_args(run)
    for arg in args:
      self.options.add_argument(arg)
    self.options.binary_location = str(self.path)
    logging.info(f"STARTING BROWSER: args: {shlex.join(args)} "
                 f"browser: {self.path} driver: {self.driver_path}")
    stdout_log_file = self.log_file.with_suffix(".stdout.log")
    # pytype: disable=wrong-keyword-args
    service = ChromeService(executable_path=str(self.driver_path),
                            log_path=self.driver_log_file,
                            service_args=[])
    service.log_file = stdout_log_file.open('w')
    self.driver = webdriver.Chrome(options=self.options, service=service)
    # pytype: enable=wrong-keyword-args
    # Prevent debugging overhead.
    self.driver.execute_cdp_cmd('Runtime.setMaxCallStackSizeToCapture',
                                dict(size=0))
    self.driver.set_window_position(self.x, self.y)
    self.driver.set_window_size(self.width, self.height)
    self._check_browser_version()
    self._pid = self.driver.service.process.pid
    self.is_running = True

  def _check_browser_version(self):
    # Make sure the driver used the provided chrome binary:
    if self.version_number == 0:
      return
    used_major_version = (self.driver.capabilities.get('browserVersion')
                          or self.driver.capabilities['version']).split('.')[0]
    assert int(used_major_version) == self.version_number, (
        f"chromedriver used wrong browser version: "
        f"{used_major_version} != {self.version_number}")

class SafariMeta(type):
  @property
  def default(cls):
    return cls('Safari', cls.default_path)

  @property
  def default_path(cls):
    return Path('/Applications/Safari.app')

  @property
  def technology_preview(cls):
    return cls('Safari Tech Preview', cls.technology_preview_path)

  @property
  def technology_preview_path(cls):
    return Path('/Applications/Safari Technology Preview.app')

class Safari(Browser, metaclass=SafariMeta):

  def __init__(self,
               label: str,
               path: Path,
               flags: FlagsInitialDataType = None,
               cache_dir : Optional[Path] = None):
    super().__init__(label, path, flags, type="safari")
    assert helper.platform.is_macos, "Safari only works on MacOS"
    bundle_name = self.path.stem.replace(' ', '')
    assert cache_dir is None, "Cannot set custom cache dir for Safari"
    self.cache_dir = Path(
        f'~/Library/Containers/com.apple.{bundle_name}/Data/Library/Caches'
    ).expanduser()
    self.default_page = 'about://blank'

  def _extract_version(self):
    app_path = self.path.parents[2]
    version_string = helper.platform.sh_stdout('mdls', '-name',
                                               'kMDItemVersion', app_path)
    # Sample output: 'kMDItemVersion = "14.1"' => "14.1"
    return re.findall(r'[\d\.]+', version_string)[0]

  def start(self, run):
    runner = run.runner
    assert not self.is_running
    runner.exec_apple_script(f'''
tell application "{self.app_name}"
  activate
end tell
    ''')
    runner.wait(1)
    runner.exec_apple_script(f'''
tell application "{self.app_name}"
  tell application "System Events"
      to click menu item "New Private Window"
      of menu "File" of menu bar 1
      of process "{self.bin_name}"
  set URL of current tab of front window to "{self.default_page}"
  set the bounds of the first window
      to {{{self.x},{self.y},{self.width},{self.height}}}
  tell application "System Events"
      to keystroke "e" using {{command down, option down}}
  tell application "System Events"
      to click menu item 1 of menu 2 of menu bar 1
      of process "{self.bin_name}"
  tell application "System Events"
      to set position of window 1
      of process "{self.bin_name}" to {400, 400}
end tell
    ''')
    runner.wait(2)
    self.is_running = True

  def show_page(self, runner, page):
    super().show_page(runner, page)
    runner.exec_apple_script(f'''
tell application "{self.app_name}"
    activate
    tell application "System Events"
        to click button 1 of window 1 of process "{self.bin_name}"
end tell
    ''')

  def show_url(self, runner, url):
    runner.exec_apple_script(f'''
tell application "{self.app_name}"
    activate
    set URL of current tab of front window to "{url}"
end tell
    ''')


class SafariWebDriver(WebdriverMixin, Safari):
  def __init__(self, label:str, path:Path, flags:FlagsInitialDataType=None,
          cache_dir : Optional[Path] =None):
    super().__init__(label, path, flags, cache_dir)
    self._find_driver()
    self._check_driver()

  def _find_driver(self):
    self.driver_path = self.path.parent / 'safaridriver'
    if not self.driver_path.exists():
      # The system-default Safari version doesn't come with the driver
      self.driver_path = Path("/usr/bin/safaridriver")
    assert self.driver_path.exists(
    ), f'safari driver "{self.driver_path}" does not exist.'

  def _check_driver(self):
    # The bundled driver is always ok
    for parent in self.driver_path.parents:
      if parent == self.path.parent:
        return True
    version = helper.platform.sh_stdout(self.driver_path, '--version')
    assert str(self.version_number) in version, \
        f"safaridriver={self.driver_path} version='{version}' "\
        f" doesn't match safari version={self.version_number}"

  def start(self, run):
    runner = run.runner
    assert not self.is_running
    capabilities = DesiredCapabilities.SAFARI.copy()
    capabilities['safari.cleanSession'] = 'true'
    # Enable browser logging
    capabilities['safari:diagnose'] = 'true'
    if 'Technology Preview' in self.app_name:
      capabilities['browserName'] = 'Safari Technology Preview'
    self.driver = webdriver.Safari(executable_path=str(self.driver_path),
                                   desired_capabilities=capabilities)
    self.driver.set_window_position(self.x, self.y)
    self.driver.set_window_size(self.width, self.height)
    logs = Path("~/Library/Logs/com.apple.WebDriver/").expanduser(
    ) / self.driver.session_id
    self.log_file = list(logs.glob("safaridriver*"))[0]
    assert self.log_file.is_file()
    self.show_url(runner, 'about://blank')
    self._pid = self.driver.service.process.pid
    self.is_running = True

  def clear_cache(self, runner):
    pass
