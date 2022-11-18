#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import os
import sys
import glob
from pathlib import Path
USE_PYTHON3 = True


def CheckChangeOnUpload(input_api, output_api):
  results = []

  # Validate that all the files have the license header
  results.extend(
      input_api.canned_checks.CheckLicense(
          input_api, output_api, project_name='Chromium'))

  # Validate the vpython spec
  results.extend(
      input_api.RunTests(
          input_api.canned_checks.CheckVPythonSpec(input_api, output_api)))
  # TODO: It will be good to add pylint checks here.
  # Currently the code has a bunch of pylint errors that need to be fixed
  # before we can enable pylint presubmit check.
  # Uncomment the line below to enable the pylint presubmit check.
  #
  # pylint_checks = input_api.canned_checks.GetPylint(input_api, output_api)
  # results += input_api.RunTests(pylint_checks)
  # Run Python unittests.
  test_file_pattern = r'.*test_.*\.py$'

  tests = input_api.canned_checks.GetUnitTestsRecursively(
      input_api,
      output_api,
      '.', [test_file_pattern], [],
      run_on_python3=True,
      run_on_python2=False,
      skip_shebang_check=True)

  results.extend(input_api.RunTests(tests))

  return results


def CheckChangeOnCommit(input_api, output_api):
  return CheckChangeOnUpload(input_api, output_api)
