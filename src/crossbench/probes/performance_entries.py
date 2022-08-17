# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from crossbench.probes import json


class PerformanceEntriesProbe(json.JsonResultProbe):
  """
  Extract all JavaScript PerformanceEntry [1] from a website.
  Website owners can define more entries via `performance.mark()`.

  [1] https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry
  """
  NAME = "performance.entries"

  def is_compatible(self, browser):
    return hasattr(browser, 'js')

  def to_json(self, actions):
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
