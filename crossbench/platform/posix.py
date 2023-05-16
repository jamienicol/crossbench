# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from functools import lru_cache
import pathlib
from typing import Union
from .platform import Platform


class PosixPlatform(Platform, metaclass=abc.ABCMeta):

  def app_version(self, app_path: pathlib.Path) -> str:
    assert app_path.exists(), f"Binary {app_path} does not exist."
    return self.sh_stdout(app_path, "--version")

  @property
  @lru_cache
  def version(self) -> str:
    return self.sh_stdout("uname", "-r").strip()

  def cat(self, file: Union[str, pathlib.Path], encoding: str = "utf-8") -> str:
    if self.is_remote:
      return self.sh_stdout("cat", file, encoding=encoding)
    with pathlib.Path(file).open(encoding=encoding) as f:
      return f.read()
