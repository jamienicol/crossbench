# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
import argparse
import math
import pathlib


def parse_path(str_value: str) -> pathlib.Path:
  try:
    path = pathlib.Path(str_value).expanduser()
  except RuntimeError as e:
    raise argparse.ArgumentTypeError(f"Invalid Path '{str_value}': {e}") from e
  if not path.exists():
    raise argparse.ArgumentTypeError(f"Path '{path}', does not exist.")
  return path


def parse_file_path(str_value: str) -> pathlib.Path:
  path = parse_path(str_value)
  if not path.is_file():
    raise argparse.ArgumentTypeError(f"Path '{path}', is not a file.")
  return path


def parse_dir_path(str_value: str) -> pathlib.Path:
  path = parse_path(str_value)
  if not path.is_dir():
    raise argparse.ArgumentTypeError(f"Path '{path}', is not a file.")
  return path


def parse_positive_float(value: str) -> float:
  value_f = float(value)
  if not math.isfinite(value_f) or value_f < 0:
    raise argparse.ArgumentTypeError(
        f"Expected positive value but got: {value_f}")
  return value_f
