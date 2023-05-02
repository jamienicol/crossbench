# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import pathlib

from .platform import Platform


class PosixPlatform(Platform, metaclass=abc.ABCMeta):

  def app_version(self, app_path: pathlib.Path) -> str:
    assert app_path.exists(), f"Binary {app_path} does not exist."
    return self.sh_stdout(app_path, "--version")
