# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from crossbench.probes.probe import Probe, ProbeResultDict, ProbeResultType  # isort:skip


from crossbench.probes.json import JsonResultProbe

from .config import ProbeConfigParser
from .performance_entries import PerformanceEntriesProbe
from .power_sampler import PowerSamplerProbe
from .profiling import ProfilingProbe
from .runner import (RunDurationsProbe, RunResultsSummaryProbe,
                     RunRunnerLogProbe)
from .system_stats import SystemStatsProbe
from .tracing import TracingProbe
from .v8 import V8BuiltinsPGOProbe, V8LogProbe, V8RCSProbe
from .video import VideoProbe

ABSTRACT_PROBES = (Probe, JsonResultProbe)

# Probes that are not user-configurable
INTERNAL_PROBES = (
    RunResultsSummaryProbe,
    RunRunnerLogProbe,
)

# Probes that can be used on arbitrary stories and may be user configurable.
GENERAL_PURPOSE_PROBES = (
    PerformanceEntriesProbe,
    PowerSamplerProbe,
    ProfilingProbe,
    SystemStatsProbe,
    TracingProbe,
    V8BuiltinsPGOProbe,
    V8LogProbe,
    V8RCSProbe,
    VideoProbe,
)

for probe_cls in GENERAL_PURPOSE_PROBES:
  assert probe_cls.IS_GENERAL_PURPOSE, (
      f"Probe {probe_cls} should be marked for GENERAL_PURPOSE")
  assert probe_cls.NAME

for probe_cls in INTERNAL_PROBES:
  assert not probe_cls.IS_GENERAL_PURPOSE, (
      f"Internal Probe {probe_cls} should not marked for GENERAL_PURPOSE")
  assert probe_cls.NAME
