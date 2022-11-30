# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import logging
import pathlib
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence

import selenium.common.exceptions
from selenium import webdriver

import crossbench
from crossbench.browsers.base import Browser

#TODO: fix imports
cb = crossbench

if TYPE_CHECKING:
  import crossbench.runner


class WebdriverMixin(Browser):
  _driver: webdriver.Remote
  _driver_path: Optional[pathlib.Path]
  _driver_pid: int
  log_file: Optional[pathlib.Path]

  @property
  def driver_log_file(self) -> pathlib.Path:
    log_file = self.log_file
    assert log_file
    return log_file.with_suffix(".driver.log")

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
    details: Dict[str, Any] = super().details_json()
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
        # pylint: disable=raise-missing-from
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
      # pylint: disable=raise-missing-from
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
        return
      # Sometimes a second quit is needed, ignore any warnings there
      try:
        self._driver.quit()
      except Exception as e:  # pylint: disable=broad-except
        logging.debug("Driver raised exception on quit: %s\n%s", e,
                      traceback.format_exc())
        pass
      return
    except Exception as e:  # pylint: disable=broad-except
      logging.debug("Could not quit browser: %s\n%s", e, traceback.format_exc())
    finally:
      self._is_running = False
    return


class RemoteWebDriver(WebdriverMixin, Browser):
  """Represent a remote WebDriver that has already been started"""

  def __init__(self, label: str, driver: webdriver.Remote):
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
