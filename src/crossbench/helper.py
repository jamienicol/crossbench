# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from abc import ABC, abstractmethod
from datetime import datetime
from datetime import timedelta
import logging
import os
from pathlib import Path
import platform as py_platform
import shlex
import subprocess
import sys
import time
import traceback
import urllib
import urllib.request

from typing import Iterable, Optional, Dict

import shutil

import psutil

if not hasattr(shlex, "join"):
  raise Exception("Please update to python v3.8 that has shlex.join")


class TTYColor:
  CYAN = '\033[1;36;6m'
  PURPLE = '\033[1;35;5m'
  BLUE = '\033[38;5;4m'
  YELLOW = '\033[38;5;3m'
  GREEN = '\033[38;5;2m'
  RED = '\033[38;5;1m'
  BLACK = '\033[38;5;0m'

  BOLD = '\033[1m'
  UNDERLINE = '\033[4m'
  REVERSED = '\033[7m'
  RESET = '\033[0m'


def implies(a, b):
  return not (a) or b


def group_by(collection, key, value=None, group=None):
  """
  Works similar to itertools.groupby but does a global, SQL-style grouping
  instead of a line-by-line basis like uniq.

  key:   a function that returns the grouping key for a group
  group: a function that accepts a group_key and returns a group object that
    has an append() method.
  """
  assert key, "No key function provided"
  key_fn = key
  value_fn = value
  group_fn = group
  groups = {}
  for item in collection:
    group_key = key_fn(item)
    if value_fn:
      item = value_fn(item)
    if group_key not in groups:
      if group_fn:
        new_group = groups[group_key] = group_fn(group_key)
        new_group.append(item)
      else:
        groups[group_key] = [item]
    else:
      groups[group_key].append(item)
  # sort keys as well for more predictable behavior
  items = sorted(groups.items(), key=str)
  return dict(items)


def sort_by_file_size(files):
  return sorted(files, key=lambda f: (-f.stat().st_size, f.name))


SIZE_UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB']


def get_file_size(file, digits=2) -> str:
  size = file.stat().st_size
  unit_index = 0
  divisor = 1024
  while (unit_index < len(SIZE_UNITS)) and size >= divisor:
    unit_index += 1
    size /= divisor
  return f"{size:.{digits}f} {SIZE_UNITS[unit_index]}"


def get_subclasses(cls):
  for subclass in cls.__subclasses__():
    yield subclass
    yield from get_subclasses(subclass)


class Platform(ABC):
  @classmethod
  def instance(cls):
    if sys.platform == 'linux':
      return LinuxPlatform()
    elif sys.platform == 'darwin':
      return OSXPlatform()
    else:
      raise Exception("Unsupported Platform")

  @property
  def machine(self):
    return py_platform.machine()

  @property
  def is_arm64(self) -> bool:
    return self.machine == 'arm64'

  @property
  def is_macos(self) -> bool:
    return False

  @property
  def is_linux(self) -> bool:
    return False

  @property
  def is_win(self) -> bool:
    return False

  @property
  def is_battery_powered(self) -> bool:
    if not psutil.sensors_battery:
      return False
    status = psutil.sensors_battery()
    if not status:
      return False
    return status.power_plugged

  def find_app_binary_path(self, app_path):
    return app_path

  def sleep(self, seconds):
    if isinstance(seconds, timedelta):
      seconds = seconds.total_seconds()
    if seconds == 0:
      return
    logging.info('WAIT %ss', seconds)
    time.sleep(seconds)

  def sh_stdout(self, *args, shell=False, quiet=False) -> str:
    completed_process = self.sh(*args,
                                shell=shell,
                                capture_output=True,
                                quiet=quiet)
    return completed_process.stdout.decode()

  def popen(self,
            *args,
            shell=False,
            stdout=None,
            stderr=None,
            stdin=None,
            quiet=False) -> subprocess.Popen:
    if not quiet:
      logging.debug('SHELL: %s', shlex.join(map(str, args)))
      logging.debug('CWD: %s', os.getcwd())
    return subprocess.Popen(args=args,
                            shell=shell,
                            stdin=stdin,
                            stderr=stderr,
                            stdout=stdout)

  def sh(self,
         *args,
         shell=False,
         capture_output=False,
         stdout=None,
         stderr=None,
         stdin=None,
         quiet=False) -> subprocess.CompletedProcess:
    if not quiet:
      logging.debug('SHELL: %s', shlex.join(map(str, args)))
      logging.debug('CWD: %s', os.getcwd())
    process = subprocess.run(args=args,
                             shell=shell,
                             stdin=stdin,
                             stdout=stdout,
                             stderr=stderr,
                             capture_output=capture_output)
    if process.returncode != 0:
      raise SubprocessError(process)
    return process

  def terminate(self, proc_pid):
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
      proc.terminate()
    process.terminate()

  def log(self, *messages, level=2, color=TTYColor.GREEN):
    messages = " ".join(map(str, messages))
    if level == 3:
      level = logging.DEBUG
    if level == 2:
      level = logging.INFO
    if level == 1:
      level = logging.WARNING
    if level == 0:
      level = logging.ERROR
    logging.log(level, messages)

  def get_relative_cpu_speed(self) -> float:
    return 1

  def is_thermal_throttled(self) -> bool:
    return self.get_relative_cpu_speed() < 1

  @abstractmethod
  def get_hardware_details(self):
    pass

  def download_to(self, url, path):
    logging.info('DOWNLOAD: %s\n       TO: %s', url, path)
    assert not path.exists(), f"Download destination {path} exists already."
    urllib.request.urlretrieve(url, path)
    assert path.exists(), \
        f"Downloading {url} failed. Downloaded file {path} doesn't exist."
    return path

  def concat_files(self, inputs: Iterable[Path], output: Path) -> Path:
    with output.open("w") as output_f:
      for input_file in inputs:
        assert input_file.is_file()
        with input_file.open() as input_f:
          shutil.copyfileobj(input_f, output_f)
    return output


class SubprocessError(subprocess.CalledProcessError):
  """ Custom version that also prints stderr for debugging"""

  def __init__(self, process):
    super().__init__(process.returncode, shlex.join(map(str, process.args)),
                     process.stdout, process.stderr)

  def __str__(self):
    super_str = super().__str__()
    if not self.stderr:
      return super_str
    return f"{super_str}\nstderr:{self.stderr.decode()}"


class UnixPlatform(Platform):
  pass


class OSXPlatform(UnixPlatform):
  @property
  def is_macos(self) -> bool:
    return True

  @property
  def short_name(self):
    return 'mac'

  def find_app_binary_path(self, app_path) -> Path:
    binaries = (app_path / 'Contents' / 'MacOS').iterdir()
    binaries = [path for path in binaries if path.is_file()]
    if len(binaries) != 1:
      raise Exception(f'Invalid number of binaries found: {binaries}')
    return binaries[0]

  def search_binary(self, app_name) -> Optional[Path]:
    try:
      app_path = Path('/Applications') / f"{app_name}.app"
      bin_path = self.find_app_binary_path(app_path)
      if not bin_path.exists():
        return None
      return bin_path
    except Exception as e:
      return None

  def exec_apple_script(self, script):
    print(script)
    return self.sh('/usr/bin/osascript', '-e', script)

  def get_relative_cpu_speed(self) -> float:
    try:
      lines = self.sh_stdout('pmset', '-g', 'therm').split()
      for index, line in enumerate(lines):
        if line == 'CPU_Speed_Limit':
          return int(lines[index + 2]) / 100.0
    except Exception:
      traceback.print_exc(file=sys.stdout)
    return 1

  def get_hardware_details(self):
    system_profiler = self.sh_stdout('system_profiler', 'SPHardwareDataType')
    sysctl_machdep_cpu = self.sh_stdout('sysctl', 'machdep.cpu')
    sysctl_hw = self.sh_stdout('sysctl', 'hw')
    return system_profiler + sysctl_machdep_cpu + sysctl_hw

  def disable_crowdstrike(self):
    falconctl = Path('/Applications/Falcon.app/Contents/Resources/falconctl')
    if not falconctl.exists():
      logging.debug("You're fine, falconctl or %s are not installed.",
                    falconctl)
    else:
      self.sh('sudo', falconctl, 'unload')


class LinuxPlatform(UnixPlatform):
  SEARCH_PATHS = (
      Path("/usr/local/sbin"),
      Path("/usr/local/bin"),
      Path("/usr/sbin"),
      Path("/usr/bin"),
      Path("/sbin"),
      Path("/bin"),
      Path("/opt/google"),
  )

  @property
  def is_linux(self) -> bool:
    return True

  @property
  def short_name(self):
    return 'linux'

  def get_hardware_details(self):
    lscpu = self.sh_stdout('lscpu')
    inxi = ""
    try:
      inxi = self.sh_stdout('inxi')
    except Exception:
      return lscpu
    return f"{inxi}\n{lscpu}"

  def search_binary(self, bin_name) -> Optional[Path]:
    for path in self.SEARCH_PATHS:
      bin_path = path / bin_name
      if bin_path.exists():
        return bin_path
    return None


platform = Platform.instance()
log = platform.log

# =============================================================================


def urlopen(url):
  try:
    return urllib.request.urlopen(url)
  except urllib.error.HTTPError as e:
    log(f"Could not load url={url}")
    raise e


# =============================================================================


class ChangeCWD:
  def __init__(self, destination):
    self.new_dir = destination
    self.prev_dir = None

  def __enter__(self):
    self.prev_dir = os.getcwd()
    os.chdir(self.new_dir)

  def __exit__(self, exc_type, exc_value, exc_traceback):
    os.chdir(self.prev_dir)


class SystemSleepPreventer:
  """
  Prevent the system from going to sleep while running the benchmark.
  """

  def __init__(self):
    self._process = None

  def __enter__(self):
    if platform.is_macos:
      self._process = platform.popen('caffeinate', '-imdsu')
    # TODO: Add linux support

  def __exit__(self, exc_type, exc_value, exc_traceback):
    if self._process is not None:
      self._process.kill()


class TimeScope:
  """
  Measures and logs the time spend during the lifetime of the TimeScope.
  """
  def __init__(self, message:str, level=3):
    self._message = message
    self._level = level
    self._start = None

  def __enter__(self):
    self._start = datetime.now()

  def __exit__(self, exc_type, exc_value, exc_traceback):
    diff = datetime.now() - self._start
    log(f"{self._message} duration={diff}", level=self._level)


class wait_range:
  def __init__(self,
               min=0.1,
               timeout=10,
               factor=1.01,
               max=10,
               max_iterations=None):
    assert 0 < min
    self.min = timedelta(seconds=min)
    assert min <= max
    self.max = timedelta(seconds=max)
    assert 1.0 < factor
    self.factor = factor
    assert 0 < timeout
    self.timeout = timedelta(seconds=timeout)
    self.current = self.min
    assert max_iterations is None or max_iterations > 0
    self.max_iterations = max_iterations

  def __iter__(self):
    i = 0
    while self.max_iterations is None or i < self.max_iterations:
      yield self.current
      self.current = min(self.current * self.factor, self.max)
      i += 1


def wait_with_backoff(range):
  assert isinstance(range, wait_range)
  start = datetime.now()
  timeout = range.timeout
  duration = 0
  for sleep_for in range:
    duration = datetime.now() - start
    if duration > range.timeout:
      raise TimeoutError(f"Waited for {duration}")
    time_left = timeout - duration
    yield duration.total_seconds(), time_left.total_seconds()
    platform.sleep(sleep_for.total_seconds())


class Durations:
  """
  Helper object to track durations.
  """

  def __init__(self):
    self._durations : Dict[str, timedelta] = {}

  def __getitem__(self, name) -> timedelta:
    return self._durations[name]

  def __setitem__(self, name, duration: timedelta):
    assert name not in self._durations, (f"Cannot set '{name}' duration twice!")
    self._durations[name] = duration

  class _DurationMeasureContext:
    def __init__(self, durations, name):
      self._start_time = None
      self._durations = durations
      self._name = name

    def __enter__(self):
      self._start_time = datetime.now()

    def __exit__(self, exc_type, exc_value, traceback):
      delta = datetime.now() - self._start_time
      self._durations[self._name] = delta

  def measure(self, name) -> "_DurationMeasureContext":
    assert name not in self._durations, (
        f"Cannot measure '{name}' duration twice!")
    return self._DurationMeasureContext(self, name)

  def to_json(self) -> Dict[str, float]:
    return {
        name: self._durations[name].total_seconds()
        for name in sorted(self._durations.keys())
    }
