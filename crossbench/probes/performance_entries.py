# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

from typing import TYPE_CHECKING

import crossbench
from crossbench.probes import json

#TODO: fix imports
cb = crossbench

if TYPE_CHECKING:
  import crossbench.browsers
  import crossbench.runner


class PerformanceEntriesProbe(json.JsonResultProbe):
  """
  Extract all JavaScript PerformanceEntry [1] from a website.
  Website owners can define more entries via `performance.mark()`.

  [1] https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry
  """
  NAME = "performance.entries"

  def is_compatible(self, browser: cb.browsers.Browser):
    return hasattr(browser, "js")

  def to_json(self, actions: cb.runner.Actions):
    return actions.js("""
      let data = { __proto__: null, paint: {}, mark: {}};
      for (let entryType of Object.keys(data)) {
        for (let entry of performance.getEntriesByType(entryType)) {
           const typeData = data[entryType];
           let values = typeData[entry.name];
           if (values === undefined) {
             values = typeData[entry.name] = {startTime:[], duration:[]};
           }
           for (let metricName of Object.keys(values)) {
            values[metricName].push(entry[metricName]);
          }
        }
      }
      return data;
      """)
