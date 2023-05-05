# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import collections.abc
import datetime as dt
import enum
import logging
import os
import pathlib
import platform as py_platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

import psutil


class Environ(collections.abc.MutableMapping, metaclass=abc.ABCMeta):
  pass


class LocalEnviron(Environ):

  def __init__(self) -> None:
    self._environ = os.environ

  def __getitem__(self, key: str) -> str:
    return self._environ.__getitem__(key)

  def __setitem__(self, key: str, item: str) -> None:
    self._environ.__setitem__(key, item)

  def __delitem__(self, key: str) -> None:
    self._environ.__delitem__(key)

  def __iter__(self) -> Iterator[str]:
    return self._environ.__iter__()

  def __len__(self) -> int:
    return self._environ.__len__()


class MachineArch(enum.Enum):
  IA32 = ("ia32", "intel", 32)
  X64 = ("x64", "intel", 64)
  ARM_32 = ("arm32", "arm", 32)
  ARM_64 = ("arm64", "arm", 64)

  def __init__(self, name, arch, bits):
    self.identifier = name
    self.arch = arch
    self.bits = bits

  @property
  def is_arm(self) -> bool:
    return self.arch == "arm"

  @property
  def is_intel(self) -> bool:
    return self.arch == "intel"

  @property
  def is_32bit(self) -> bool:
    return self.bits == 32

  @property
  def is_64bit(self) -> bool:
    return self.bits == 64

  def __str__(self) -> str:
    return self.identifier


class SubprocessError(subprocess.CalledProcessError):
  """ Custom version that also prints stderr for debugging"""

  def __init__(self, process) -> None:
    super().__init__(process.returncode, shlex.join(map(str, process.args)),
                     process.stdout, process.stderr)

  def __str__(self) -> str:
    super_str = super().__str__()
    if not self.stderr:
      return super_str
    return f"{super_str}\nstderr:{self.stderr.decode()}"


class Platform(abc.ABC):

  @property
  @abc.abstractmethod
  def name(self) -> str:
    pass

  @property
  @abc.abstractmethod
  def version(self) -> str:
    pass

  @property
  @abc.abstractmethod
  def device(self) -> str:
    pass

  @property
  @abc.abstractmethod
  def cpu(self) -> str:
    pass

  @property
  def full_version(self) -> str:
    return f"{self.name} {self.version} {self.machine}"

  def __str__(self) -> str:
    return ".".join(self.key) + (".remote" if self.is_remote else ".local")

  @property
  def is_remote(self) -> bool:
    return False

  @property
  def host_platform(self) -> Platform:
    return self

  @property
  def machine(self) -> MachineArch:
    assert not self.is_remote, (
        f"Operation not supported yet on remote platform: {self.name}")
    raw = py_platform.machine()
    if raw in ("i386", "i686", "x86", "ia32"):
      return MachineArch.IA32
    if raw in ("x86_64", "AMD64"):
      return MachineArch.X64
    if raw in ("arm64", "aarch64"):
      return MachineArch.ARM_64
    if raw in ("arm"):
      return MachineArch.ARM_32
    raise NotImplementedError(f"Unsupported machine type: {raw}")

  @property
  def is_ia32(self) -> bool:
    return self.machine == MachineArch.IA32

  @property
  def is_x64(self) -> bool:
    return self.machine == MachineArch.X64

  @property
  def is_arm64(self) -> bool:
    return self.machine == MachineArch.ARM_64

  @property
  def key(self) -> Tuple[str, str]:
    return (self.name, str(self.machine))

  @property
  def is_macos(self) -> bool:
    return False

  @property
  def is_linux(self) -> bool:
    return False

  @property
  def is_android(self) -> bool:
    return False

  @property
  def is_posix(self) -> bool:
    return self.is_macos or self.is_linux or self.is_android

  @property
  def is_win(self) -> bool:
    return False

  @property
  def environ(self) -> Environ:
    assert not self.is_remote, "Not implemented yet on remote"
    return LocalEnviron()

  @property
  def is_battery_powered(self) -> bool:
    if not psutil.sensors_battery:
      return False
    status = psutil.sensors_battery()
    if not status:
      return False
    return not status.power_plugged

  def search_app(self, app_path: pathlib.Path) -> Optional[pathlib.Path]:
    return self.search_binary(app_path)

  @abc.abstractmethod
  def search_binary(self, app_path: pathlib.Path) -> Optional[pathlib.Path]:
    pass

  @abc.abstractmethod
  def app_version(self, app_path: pathlib.Path) -> str:
    pass

  @property
  def has_display(self) -> bool:
    return True

  def sleep(self, seconds: Union[int, float, dt.timedelta]) -> None:
    if isinstance(seconds, dt.timedelta):
      seconds = seconds.total_seconds()
    if seconds == 0:
      return
    logging.debug("WAIT %ss", seconds)
    time.sleep(seconds)

  def which(self, binary_name: str) -> Optional[pathlib.Path]:
    # TODO(cbruni): support remote platforms
    result = shutil.which(binary_name)
    if not result:
      return None
    return pathlib.Path(result)

  def processes(self,
                attrs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    # TODO(cbruni): support remote platforms
    assert not self.is_remote, "Only local platform supported"
    return [
        p.info  # pytype: disable=attribute-error
        for p in psutil.process_iter(attrs=attrs)
    ]

  def process_running(self, process_name_list: List[str]) -> Optional[str]:
    # TODO(cbruni): support remote platforms
    for proc in psutil.process_iter():
      try:
        if proc.name().lower() in process_name_list:
          return proc.name()
      except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return None

  def process_children(self,
                       parent_pid: int,
                       recursive: bool = False) -> List[Dict[str, Any]]:
    # TODO(cbruni): support remote platforms
    try:
      process = psutil.Process(parent_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
      return []
    return [p.as_dict() for p in process.children(recursive=recursive)]

  def process_info(self, pid: int) -> Optional[Dict[str, Any]]:
    # TODO(cbruni): support remote platforms
    try:
      return psutil.Process(pid).as_dict()
    except psutil.NoSuchProcess:
      return None

  def foreground_process(self) -> Optional[Dict[str, Any]]:
    return None

  def terminate(self, proc_pid: int) -> None:
    # TODO(cbruni): support remote platforms
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
      proc.terminate()
    process.terminate()

  def sh_stdout(self,
                *args,
                shell: bool = False,
                quiet: bool = False,
                encoding: str = "utf-8") -> str:
    completed_process = self.sh(
        *args, shell=shell, capture_output=True, quiet=quiet)
    return completed_process.stdout.decode(encoding)

  def popen(self,
            *args,
            shell: bool = False,
            stdout=None,
            stderr=None,
            stdin=None,
            env=None,
            quiet: bool = False) -> subprocess.Popen:
    if not quiet:
      logging.debug("SHELL: %s", shlex.join(map(str, args)))
      logging.debug("CWD: %s", os.getcwd())
    return subprocess.Popen(
        args=args,
        shell=shell,
        stdin=stdin,
        stderr=stderr,
        stdout=stdout,
        env=env)

  def sh(self,
         *args,
         shell: bool = False,
         capture_output: bool = False,
         stdout=None,
         stderr=None,
         stdin=None,
         env=None,
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
        env=env,
        capture_output=capture_output,
        check=False)
    if process.returncode != 0:
      raise SubprocessError(process)
    return process

  def exec_apple_script(self, script: str) -> str:
    raise NotImplementedError("AppleScript is only available on MacOS")

  def log(self, *messages: Any, level: int = 2) -> None:
    message_str = " ".join(map(str, messages))
    if level == 3:
      level = logging.DEBUG
    if level == 2:
      level = logging.INFO
    if level == 1:
      level = logging.WARNING
    if level == 0:
      level = logging.ERROR
    logging.log(level, message_str)

  # TODO(cbruni): split into separate list_system_monitoring and
  # disable_system_monitoring methods
  def check_system_monitoring(self, disable: bool = False) -> bool:
    # pylint: disable=unused-argument
    return True

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
        "physical cores":
            psutil.cpu_count(logical=False),
        "logical cores":
            psutil.cpu_count(logical=True),
        "usage":
            psutil.cpu_percent(  # pytype: disable=attribute-error
                percpu=True, interval=0.1),
        "total usage":
            psutil.cpu_percent(),
        "system load":
            psutil.getloadavg(),
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

  def download_to(self, url: str, path: pathlib.Path) -> pathlib.Path:
    logging.debug("DOWNLOAD: %s\n       TO: %s", url, path)
    assert not path.exists(), f"Download destination {path} exists already."
    try:
      urllib.request.urlretrieve(url, path)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
      raise OSError(f"Could not load {url}") from e
    assert path.exists(), (
        f"Downloading {url} failed. Downloaded file {path} doesn't exist.")
    return path

  def concat_files(self, inputs: Iterable[pathlib.Path],
                   output: pathlib.Path) -> pathlib.Path:
    with output.open("w", encoding="utf-8") as output_f:
      for input_file in inputs:
        assert input_file.is_file()
        with input_file.open(encoding="utf-8") as input_f:
          shutil.copyfileobj(input_f, output_f)
    return output

  def set_main_display_brightness(self, brightness_level: int) -> None:
    raise NotImplementedError(
        "Implementation is only available on MacOS for now")

  def get_main_display_brightness(self) -> int:
    raise NotImplementedError(
        "Implementation is only available on MacOS for now")

  def check_autobrightness(self) -> bool:
    raise NotImplementedError(
        "Implementation is only available on MacOS for now")
