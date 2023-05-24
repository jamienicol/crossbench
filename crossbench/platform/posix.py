# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from functools import lru_cache
import pathlib
from typing import List, Optional, Union
from .platform import Platform


class PosixPlatform(Platform, metaclass=abc.ABCMeta):
  # pylint: disable=locally-disabled, redefined-builtin

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
    return super().cat(file, encoding)

  def rm(self, path: Union[str, pathlib.Path], dir: bool = False) -> None:
    if self.is_remote:
      if dir:
        self.sh("rm", "-rf", path)
      else:
        self.sh("rm", path)
    else:
      super().rm(path, dir)

  def mkdir(self, path: Union[str, pathlib.Path]) -> None:
    if self.is_remote:
      self.sh("mkdir", "-p", path)
    else:
      super().mkdir(path)

  def mkdtemp(self,
              prefix: Optional[str] = None,
              dir: Optional[Union[str, pathlib.Path]] = None) -> pathlib.Path:
    if self.is_remote:
      return self._mktemp_sh(is_dir=True, prefix=prefix, dir=dir)
    return super().mkdtemp(prefix, dir)

  def mktemp(self,
             prefix: Optional[str] = None,
             dir: Optional[Union[str, pathlib.Path]] = None) -> pathlib.Path:
    if self.is_remote:
      return self._mktemp_sh(is_dir=False, prefix=prefix, dir=dir)
    return super().mktemp(prefix, dir)

  def _mktemp_sh(self, is_dir: bool, prefix: Optional[str],
                 dir: Optional[Union[str, pathlib.Path]]) -> pathlib.Path:
    if not dir:
      dir = self.default_tmp_dir
    template = pathlib.Path(dir) / f"{prefix}.XXXXXXXXXXX"
    args: List[str] = ["mktemp"]
    if is_dir:
      args.append("-d")
    args.append(str(template))
    result = self.sh_stdout(*args)
    return pathlib.Path(result.strip())
