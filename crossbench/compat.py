# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
""" A collection of helpers that exist in future python versions. """

from __future__ import annotations

import enum
import sys

if sys.version_info >= (3, 11):
  from enum import StrEnum
else:

  class StrEnum(str, enum.Enum):

    def __str__(self) -> str:
      return str(self.value)


__all__ = ("StrEnum",)
