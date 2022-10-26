# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import ctypes
import datetime as dt
import logging
import os
import pathlib
import platform as py_platform
import shlex
import json
import shutil
import subprocess
import sys
import time
import traceback
import urllib
import urllib.request
from typing import Any, Dict, Iterable, Optional

import psutil

if not hasattr(shlex, "join"):
  raise Exception("Please update to python v3.8 that has shlex.join")


class TTYColor:
  CYAN = "\033[1;36;6m"
  PURPLE = "\033[1;35;5m"
  BLUE = "\033[38;5;4m"
  YELLOW = "\033[38;5;3m"
  GREEN = "\033[38;5;2m"
  RED = "\033[38;5;1m"
  BLACK = "\033[38;5;0m"

  BOLD = "\033[1m"
  UNDERLINE = "\033[4m"
  REVERSED = "\033[7m"
  RESET = "\033[0m"


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


SIZE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB"]


def get_file_size(file, digits=2) -> str:
  size = file.stat().st_size
  unit_index = 0
  divisor = 1024
  while (unit_index < len(SIZE_UNITS)) and size >= divisor:
    unit_index += 1
    size /= divisor
  return f"{size:.{digits}f} {SIZE_UNITS[unit_index]}"


class Platform(abc.ABC):

  @abc.abstractproperty
  def short_name(self) -> str:
    pass

  @property
  def is_remote(self):
    return False

  @property
  def machine(self):
    return py_platform.machine()

  @property
  def is_arm64(self) -> bool:
    return self.machine == "arm64"

  @property
  def is_macos(self) -> bool:
    return False

  @property
  def is_linux(self) -> bool:
    return False

  @property
  def is_posix(self) -> bool:
    return self.is_macos or self.is_linux

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
    if isinstance(seconds, dt.timedelta):
      seconds = seconds.total_seconds()
    if seconds == 0:
      return
    logging.info("WAIT %ss", seconds)
    time.sleep(seconds)

  def which(self, binary):
    # TODO(cbruni): support remote plaforms
    return shutil.which(binary)

  def sh_stdout(self, *args, shell=False, quiet=False, encoding="utf-8") -> str:
    completed_process = self.sh(
        *args, shell=shell, capture_output=True, quiet=quiet)
    return completed_process.stdout.decode(encoding)

  def popen(self,
            *args,
            shell=False,
            stdout=None,
            stderr=None,
            stdin=None,
            quiet=False) -> subprocess.Popen:
    if not quiet:
      logging.debug("SHELL: %s", shlex.join(map(str, args)))
      logging.debug("CWD: %s", os.getcwd())
    return subprocess.Popen(
        args=args, shell=shell, stdin=stdin, stderr=stderr, stdout=stdout)

  def sh(self,
         *args,
         shell=False,
         capture_output=False,
         stdout=None,
         stderr=None,
         stdin=None,
         quiet=False) -> subprocess.CompletedProcess:
    if not quiet:
      logging.debug("SHELL: %s", shlex.join(map(str, args)))
      logging.debug("CWD: %s", os.getcwd())
    process = subprocess.run(
        args=args,
        shell=shell,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        capture_output=capture_output)
    if process.returncode != 0:
      raise SubprocessError(process)
    return process

  def exec_apple_script(self, script, quite=False):
    raise NotImplementedError("AppleScript is only available on MacOS")

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

  @abc.abstractmethod
  def disable_monitoring(self):
    pass

  def get_relative_cpu_speed(self) -> float:
    return 1

  def is_thermal_throttled(self) -> bool:
    return self.get_relative_cpu_speed() < 1

  def disk_usage(self, path: pathlib.Path) -> psutil._common.sdiskusage:
    return psutil.disk_usage(str(path))

  def cpu_usage(self) -> float:
    return 1 - psutil.cpu_times_percent().idle / 100

  def cpu_details(self) -> Dict[str, Any]:
    details = {
        "physical cores": psutil.cpu_count(logical=False),
        "logical cores": psutil.cpu_count(logical=True),
        "usage": [  # pytype: disable=attribute-error
            cpu_percent
            for cpu_percent in psutil.cpu_percent(percpu=True, interval=0.1)
        ],
        "total usage": psutil.cpu_percent(),
        "system load": psutil.getloadavg(),
    }
    try:
      cpu_freq = psutil.cpu_freq()
    except FileNotFoundError:
      # MacOS M1 fail for this some times
      return details
    details.update({
        "max frequency": f"{cpu_freq.max:.2f}Mhz",
        "min frequency": f"{cpu_freq.min:.2f}Mhz",
        "current frequency": f"{cpu_freq.current:.2f}Mhz",
    })
    return details

  def system_details(self) -> Dict[str, Any]:
    return {
        "machine": py_platform.machine(),
        "os": {
            "system": py_platform.system(),
            "release": py_platform.release(),
            "version": py_platform.version(),
            "platform": py_platform.platform(),
        },
        "python": {
            "version": py_platform.python_version(),
            "bits": "64" if sys.maxsize > 2**32 else "32",
        },
        "CPU": self.cpu_details(),
    }

  @abc.abstractmethod
  def app_version(self, bin_path: pathlib.Path) -> str:
    pass

  def download_to(self, url, path):
    logging.info("DOWNLOAD: %s\n       TO: %s", url, path)
    assert not path.exists(), f"Download destination {path} exists already."
    try:
      urllib.request.urlretrieve(url, path)
    except urllib.error.HTTPError as e:
      raise OSError(f"Could not load {url}") from e
    assert path.exists(), (
        f"Downloading {url} failed. Downloaded file {path} doesn't exist.")
    return path

  def concat_files(self, inputs: Iterable[pathlib.Path],
                   output: pathlib.Path) -> pathlib.Path:
    with output.open("w") as output_f:
      for input_file in inputs:
        assert input_file.is_file()
        with input_file.open() as input_f:
          shutil.copyfileobj(input_f, output_f)
    return output

  def set_main_display_brightness(self, brightness_level: int):
    raise NotImplementedError("Implemention is only available on MacOS for now")

  def get_main_display_brightness(self):
    raise NotImplementedError("Implemention is only available on MacOS for now")


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


class WinPlatform(Platform):
  SEARCH_PATHS = [
      pathlib.Path(os.path.expandvars("%ProgramFiles%")),
      pathlib.Path(os.path.expandvars("%ProgramFiles(x86)%")),
      pathlib.Path(os.path.expandvars("%APPDATA%")),
      pathlib.Path(os.path.expandvars("%LOCALAPPDATA%"))
  ]

  @property
  def is_win(self):
    return True

  @property
  def short_name(self):
    return "win"

  def disable_monitoring(self):
    pass

  def search_binary(self, bin_name) -> Optional[pathlib.Path]:
    for path in self.SEARCH_PATHS:
      bin_path = path / bin_name
      if bin_path.exists():
        return bin_path
    return None

  def app_version(self, bin: pathlib.Path) -> str:
    assert bin.exists(), f"Binary {bin} does not exist."
    return self.sh_stdout("powershell", "-command",
                          f"(Get-Item '{bin}').VersionInfo.ProductVersion")


class PosixPlatform(Platform, metaclass=abc.ABCMeta):

  def app_version(self, bin: pathlib.Path) -> str:
    assert bin.exists(), f"Binary {bin} does not exist."
    return self.sh_stdout(bin, "--version")


class MacOSPlatform(PosixPlatform):

  @property
  def is_macos(self):
    return True

  @property
  def short_name(self):
    return "macos"

  def find_app_binary_path(self, app_path) -> pathlib.Path:
    bin_path = app_path / "Contents" / "MacOS" / app_path.stem
    if bin_path.exists():
      return bin_path
    binaries = bin_path.parent.iterdir()
    binaries = [path for path in binaries if path.is_file()]
    if len(binaries) != 1:
      raise Exception(f"Invalid number of binaries found: {binaries}")
    return binaries[0]

  def search_binary(self, app_name) -> Optional[pathlib.Path]:
    try:
      app_path = pathlib.Path("/Applications") / f"{app_name}.app"
      bin_path = self.find_app_binary_path(app_path)
      if not bin_path.exists():
        return None
      return bin_path
    except Exception as e:
      return None

  def app_version(self, bin_path: pathlib.Path) -> str:
    assert bin_path.exists(), f"Binary {bin} does not exist."

    app_path = None
    current = bin_path
    while current != bin_path.root:
      if current.suffix == ".app":
        app_path = current
        break
      current = current.parent

    if not app_path:
      # Most likely just a cli tool"
      return self.sh_stdout(app_path, "--version")

    version_string = self.sh_stdout("mdls", "-name", "kMDItemVersion", app_path)
    # Filter output: "kMDItemVersion = "14.1"" => "14.1"
    prefix, version_string = version_string.split(" = ", maxsplit=1)
    assert version_string != "(null)", f"Didn't find app at {bin_path}"
    return version_string[1:-1]

  def exec_apple_script(self, script, quiet=False):
    if not quiet:
      logging.debug("AppleScript: %s", script)
    return self.sh("/usr/bin/osascript", "-e", script)

  def get_relative_cpu_speed(self) -> float:
    try:
      lines = self.sh_stdout("pmset", "-g", "therm").split()
      for index, line in enumerate(lines):
        if line == "CPU_Speed_Limit":
          return int(lines[index + 2]) / 100.0
    except Exception:
      traceback.print_exc(file=sys.stdout)
    return 1

  def system_details(self) -> Dict[str, Any]:
    details = super().system_details()
    details.update({
        "system_profiler":
            self.sh_stdout("system_profiler", "SPHardwareDataType"),
        "sysctl_machdep_cpu":
            self.sh_stdout("sysctl", "machdep.cpu"),
        "sysctl_hw":
            self.sh_stdout("sysctl", "hw"),
    })
    return details

  def disable_monitoring(self):
    self.disable_crowdstrike()

  def disable_crowdstrike(self):
    falconctl = pathlib.Path(
        "/Applications/Falcon.app/Contents/Resources/falconctl")
    if not falconctl.exists():
      logging.debug("You're fine, falconctl or %s are not installed.",
                    falconctl)
    else:
      logging.warn("Disabling crowdstrike monitoring:")
      self.sh("sudo", falconctl, "unload")

  def set_main_display_brightness(self, brightness_level: int):
    """Sets the main display brightness at the specified percentage by brightness_level.

    This function imitates the open-source "brightness" tool at
    https://github.com/nriley/brightness.
    Since the benchmark doesn't care about older MacOSen, multiple displays
    or other complications that tool has to consider, setting the brightness
    level boils down to calling this function for the main display.

    Args:
      brightness_level: Percentage at which we want to set screen brightness.

    Raises:
      AssertionError: An error occused when we tried to set the brightness
    """
    CoreGraphics = ctypes.CDLL(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    main_display = CoreGraphics.CGMainDisplayID()
    DisplayServices = ctypes.CDLL(
        "/System/Library/PrivateFrameworks/DisplayServices.framework"
        "/DisplayServices")
    DisplayServices.DisplayServicesSetBrightness.argtypes = [
        ctypes.c_int, ctypes.c_float
    ]
    ret = DisplayServices.DisplayServicesSetBrightness(main_display,
                                                       brightness_level / 100)
    assert ret == 0

  def get_main_display_brightness(self):
    """Gets the current brightness level of the main display .

    This function imitates the open-source "brightness" tool at
    https://github.com/nriley/brightness.
    Since the benchmark doesn't care about older MacOSen, multiple displays
    or other complications that tool has to consider, setting the brightness
    level boils down to calling this function for the main display.

    Returns:
      An int of the current percentage value of the main screen brightness

    Raises:
      AssertionError: An error occused when we tried to set the brightness
    """
    CoreGraphics = ctypes.CDLL(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    main_display = CoreGraphics.CGMainDisplayID()
    display_brightness = ctypes.c_float()
    DisplayServices = ctypes.CDLL(
        "/System/Library/PrivateFrameworks/DisplayServices.framework"
        "/DisplayServices")
    DisplayServices.DisplayServicesGetBrightness.argtypes = [
        ctypes.c_int, ctypes.POINTER(ctypes.c_float)
    ]
    ret = DisplayServices.DisplayServicesGetBrightness(
        main_display, ctypes.byref(display_brightness))

    assert ret == 0
    return round(display_brightness.value * 100)


class LinuxPlatform(PosixPlatform):
  SEARCH_PATHS = (
      pathlib.Path("/usr/local/sbin"),
      pathlib.Path("/usr/local/bin"),
      pathlib.Path("/usr/sbin"),
      pathlib.Path("/usr/bin"),
      pathlib.Path("/sbin"),
      pathlib.Path("/bin"),
      pathlib.Path("/opt/google"),
  )

  @property
  def is_linux(self):
    return True

  @property
  def short_name(self):
    return "linux"

  def disable_monitoring(self):
    pass

  def system_details(self) -> Dict[str, Any]:
    details = super().system_details()
    for info_bin in ("lscpu", "inxi"):
      if self.which(info_bin):
        details[info_bin] = self.sh_stdout(info_bin)
    return details

  def search_binary(self, bin_name) -> Optional[pathlib.Path]:
    for path in self.SEARCH_PATHS:
      bin_path = path / bin_name
      if bin_path.exists():
        return bin_path
    return None

if sys.platform == "linux":
  platform = LinuxPlatform()
elif sys.platform == "darwin":
  platform = MacOSPlatform()
elif sys.platform == "win32":
  platform = WinPlatform()
else:
  raise Exception("Unsupported Platform")

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
      self._process = platform.popen("caffeinate", "-imdsu")
    # TODO: Add linux support

  def __exit__(self, exc_type, exc_value, exc_traceback):
    if self._process is not None:
      self._process.kill()


class TimeScope:
  """
  Measures and logs the time spend during the lifetime of the TimeScope.
  """

  def __init__(self, message: str, level: int = 3):
    self._message = message
    self._level = level
    self._start: Optional[dt.datetime] = None

  def __enter__(self):
    self._start = dt.datetime.now()

  def __exit__(self, exc_type, exc_value, exc_traceback):
    assert self._start
    diff = dt.datetime.now() - self._start
    log(f"{self._message} duration={diff}", level=self._level)


class wait_range:

  def __init__(self,
               min=0.1,
               timeout=10,
               factor=1.01,
               max=10,
               max_iterations=None):
    assert 0 < min
    self.min = dt.timedelta(seconds=min)
    assert min <= max
    self.max = dt.timedelta(seconds=max)
    assert 1.0 < factor
    self.factor = factor
    assert 0 < timeout
    self.timeout = dt.timedelta(seconds=timeout)
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
  start = dt.datetime.now()
  timeout = range.timeout
  duration = 0
  for sleep_for in range:
    duration = dt.datetime.now() - start
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
    self._durations: Dict[str, dt.timedelta] = {}

  def __getitem__(self, name) -> dt.timedelta:
    return self._durations[name]

  def __setitem__(self, name, duration: dt.timedelta):
    assert name not in self._durations, (f"Cannot set '{name}' duration twice!")
    self._durations[name] = duration

  def __len__(self):
    return len(self._durations)

  class _DurationMeasureContext:

    def __init__(self, durations, name):
      self._start_time = None
      self._durations = durations
      self._name = name

    def __enter__(self):
      self._start_time = dt.datetime.now()

    def __exit__(self, exc_type, exc_value, traceback):
      delta = dt.datetime.now() - self._start_time
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
