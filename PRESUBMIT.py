#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import platform

USE_PYTHON3 = True


def CheckChangeOnUpload(input_api, output_api):
  results = []
  # Validate the vpython spec
  results += input_api.RunTests(
      input_api.canned_checks.CheckVPythonSpec(input_api, output_api))
  # Pylint
  files_to_check = [
      r'^[^\.]+\.py$',
  ]
  disabled_warnings = [
      "missing-module-docstring",
      "missing-class-docstring",
      "unused-argument",  # TODO: enable again
      "unnecessary-pass",  # TODO: enable again
      "assignment-from-none",
      "useless-super-delegation",
      "line-too-long",  # Annoying false-positives on URLs
      "cyclic-import",  # TODO: This is not working as expected yet
  ]
  pylint_checks = input_api.canned_checks.GetPylint(
      input_api,
      output_api,
      files_to_check=files_to_check,
      disabled_warnings=disabled_warnings)
  results += input_api.RunTests(pylint_checks)
  # License header checks
  results += input_api.canned_checks.CheckLicense(input_api, output_api)
  # Only run test_cli to speed up the presubmit checks
  env = os.environ.copy()
  if platform.system() == "Windows":
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + ";tests"
  else:
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + ":tests"
  results += input_api.canned_checks.RunUnitTestsInDirectory(
      input_api,
      output_api,
      directory='tests',
      env=env,
      files_to_check=[r'.*test_cli\.py$'],
      skip_shebang_check=True,
      run_on_python2=False)
  return results


def CheckChangeOnCommit(input_api, output_api):
  return CheckChangeOnUpload(input_api, output_api)
