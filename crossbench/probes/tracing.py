# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from crossbench import probes


class TracingProbe(probes.Probe):
  """
  Chromium-only Probe to collect tracing / perfetto data that can be used by
  chrome://tracing or https://ui.perfetto.dev/.

  Currently WIP
  """
  NAME = "tracing"
  FLAGS = (
      "--enable-perfetto",
      "--disable-fre",
      "--danger-disable-safebrowsing-for-crossbench",
  )

  def __init__(self, categories, startup_duration=0, output_format="json"):
    super().__init__()
    self._categories = categories
    self._startup_duration = startup_duration
    self._format = output_format
    assert self._format in ("json", "proto"), \
        f"Invalid trace output output_format={self._format}"

  def is_compatible(self, browser):
    return browser.type == "chrome"

  def attach(self, browser):
    super().attach(browser)
    # "--trace-startup-format"
    # --trace-startup-duration=
    # --trace-startup=categories
    # v--trace-startup-file=" + file_name
    pass
