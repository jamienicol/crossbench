# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import crossbench
from crossbench.probes import base

#TODO: fix imports
cb = crossbench

if TYPE_CHECKING:
  import crossbench.browsers


class TracingProbe(base.Probe):
  """
  Chromium-only Probe to collect tracing / perfetto data that can be used by
  chrome://tracing or https://ui.perfetto.dev/.

  Currently WIP
  """
  NAME = "tracing"
  FLAGS = (
      "--enable-perfetto",
      "--disable-fre",
  )

  def __init__(self,
               categories: Iterable[str],
               startup_duration: float = 0,
               output_format="json"):
    super().__init__()
    self._categories = categories
    self._startup_duration = startup_duration
    self._format = output_format
    assert self._format in ("json", "proto"), (
        f"Invalid trace output output_format={self._format}")

  def is_compatible(self, browser: cb.browsers.Browser):
    return isinstance(browser, cb.browsers.Chromium)

  def attach(self, browser: cb.browsers.Browser):
    # "--trace-startup-format"
    # --trace-startup-duration=
    # --trace-startup=categories
    # v--trace-startup-file=" + file_name
    super().attach(browser)
