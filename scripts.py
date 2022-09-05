# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys

from crossbench.cli import CrossBenchCLI


def crossbench(argv=sys.argv):
  cli = CrossBenchCLI()
  cli.run(argv[1:])