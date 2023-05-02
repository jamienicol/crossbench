# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import os
import pathlib
from typing import Any, Dict, Optional

from .posix import PosixPlatform


class LinuxPlatform(PosixPlatform):
  SEARCH_PATHS = (
      pathlib.Path("."),
      pathlib.Path("/usr/local/sbin"),
      pathlib.Path("/usr/local/bin"),
      pathlib.Path("/usr/sbin"),
      pathlib.Path("/usr/bin"),
      pathlib.Path("/sbin"),
      pathlib.Path("/bin"),
      pathlib.Path("/opt/google"),
  )

  @property
  def is_linux(self) -> bool:
    return True

  @property
  def name(self) -> str:
    return "linux"

  def check_system_monitoring(self, disable: bool = False) -> bool:
    return True

  @property
  def has_display(self) -> bool:
    return "DISPLAY" in os.environ

  def system_details(self) -> Dict[str, Any]:
    details = super().system_details()
    for info_bin in ("lscpu", "inxi"):
      if self.which(info_bin):
        details[info_bin] = self.sh_stdout(info_bin)
    return details

  def search_binary(self, app_path: pathlib.Path) -> Optional[pathlib.Path]:
    for path in self.SEARCH_PATHS:
      # Recreate Path object for easier pyfakefs testing
      result_path = pathlib.Path(path) / app_path
      if result_path.exists():
        return result_path
    return None