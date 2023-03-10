# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
from typing import Final

from .speedometer_2 import (Speedometer2Probe, Speedometer2Story,
                            Speedometer2Benchmark, ProbeClsTupleT)


class Speedometer21Probe(Speedometer2Probe):
  __doc__ = Speedometer2Probe.__doc__
  NAME: Final[str] = "speedometer_2.1"


class Speedometer21Story(Speedometer2Story):
  __doc__ = Speedometer2Story.__doc__
  NAME: Final[str] = "speedometer_2.1"
  PROBES: Final[ProbeClsTupleT] = (Speedometer21Probe,)
  URL: Final[str] = ("https://browserbench.org/Speedometer2.1/"
                     "InteractiveRunner.html")


class Speedometer21Benchmark(Speedometer2Benchmark):
  """
  Benchmark runner for Speedometer 2.1
  """
  NAME: Final[str] = "speedometer_2.1"
  DEFAULT_STORY_CLS = Speedometer21Story
