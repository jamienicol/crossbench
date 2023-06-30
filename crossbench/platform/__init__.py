# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import sys
from typing import Final

from .platform import MachineArch, Platform, SubprocessError

from .linux import LinuxPlatform
from .macos import MacOSPlatform
from .win import WinPlatform
from .android_adb import AndroidAdbPlatform, Adb


def _get_default() -> Platform:
  if sys.platform == "linux":
    return LinuxPlatform()
  if sys.platform == "darwin":
    return MacOSPlatform()
  if sys.platform == "win32":
    return WinPlatform()
  raise NotImplementedError("Unsupported Platform")


DEFAULT: Final[Platform] = _get_default()
DEFAULT_PLATFORM: Final[Platform] = DEFAULT

__all__ = (
    "DEFAULT",
    "Platform",
    "MachineArch",
    "SubprocessError",
    "AndroidAdbPlatform",
    "Adb",
)
