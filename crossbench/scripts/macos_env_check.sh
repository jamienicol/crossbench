#!/bin/bash

# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -eu

function SystemProfilerProperty()
{
  local result=$2
  local local_result=$(system_profiler $3| grep -i $1 |\
    cut -d ":" -f 2 | awk '{$1=$1};1')
  eval $result="'$local_result'"
}

function GetDisplayProperty()
{
  SystemProfilerProperty $1 $2 "SPDisplaysDataType"
}

function CompareValue()
{
  if [ "$1" != "$2" ]; then
    echo $3
    exit 127
  fi
}

CheckDisplayValue()
{
  # Query value, remove newlines.
  GetDisplayProperty $1 VALUE
  VALUE=$(echo $VALUE|tr -d '\n')

  CompareValue $VALUE $2 $3
}

function CheckEnv()
{
  # Validate display setup.
  CheckDisplayValue "Automatically adjust brightness" "No"\
    "Disable automatic brightness adjustments and unplug external monitors"
}

CheckEnv