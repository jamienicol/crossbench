# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from crossbench.probes.config import ProbeConfigParser
from crossbench.probes import Probe


class MockProbe(Probe):
  """
  Probe DOC Text
  """
  pass


class CustomArgType:

  def __init__(self, value):
    self.value = value


def custom_arg_type(value):
  return CustomArgType(value)


class TestProbeConfig(unittest.TestCase):

  def test_help_text(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("bool", type=bool)
    parser.add_argument("bool_default", type=bool, default=False)
    parser.add_argument("bool_list", type=bool, default=False, is_list=True)
    parser.add_argument("custom_type", type=custom_arg_type)
    parser.add_argument("custom_help", type=bool, help="custom help")
    help = str(parser)
    self.assertIn("Probe DOC Text", help)
    self.assertIn("bool_default", help)
    self.assertIn("bool_list", help)
    self.assertIn("custom_type", help)
    self.assertIn("custom_help", help)

  def test_bool_missing_property(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("bool_argument_name", type=bool)
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"other": True})

  def test_bool_invalid_value(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("bool_argument_name", type=bool)
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"bool_argument_name": "not a bool"})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"bool_argument_name": ""})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"bool_argument_name": {}})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"bool_argument_name": []})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"bool_argument_name": None})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"bool_argument_name": 0})

  def test_bool_default(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("bool_argument_name", type=bool, default=False)

    config_data = {}
    kwargs = parser.kwargs_from_config(config_data)
    self.assertDictEqual(config_data, {})
    self.assertDictEqual(kwargs, {"bool_argument_name": False})

    config_data = {"bool_argument_name": True}
    kwargs = parser.kwargs_from_config(config_data)
    self.assertDictEqual(config_data, {})
    self.assertDictEqual(kwargs, {"bool_argument_name": True})

  def test_bool(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("bool_argument_name", type=bool)
    config_data = {"bool_argument_name": True}
    kwargs = parser.kwargs_from_config(config_data)
    self.assertDictEqual(config_data, {})
    self.assertDictEqual(kwargs, {"bool_argument_name": True})

  def test_int_list_invalid(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("int_list", type=int, is_list=True, default=[111, 222])
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"int_list": 9})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"int_list": ["0", "1"]})
    with self.assertRaises(ValueError):
      parser.kwargs_from_config({"int_list": "0,1"})

  def test_int_list(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("int_list", type=int, is_list=True, default=[111, 222])
    kwargs = parser.kwargs_from_config({})
    self.assertDictEqual(kwargs, {"int_list": [111, 222]})

    config_data = {"int_list": [0, 1]}
    kwargs = parser.kwargs_from_config(config_data)
    self.assertDictEqual(config_data, {})
    self.assertDictEqual(kwargs, {"int_list": [0, 1]})

  def test_custom_type(self):
    parser = ProbeConfigParser(MockProbe)
    parser.add_argument("custom", type=custom_arg_type)
    config_data = {"custom": [1, 2, "stuff"]}
    kwargs = parser.kwargs_from_config(config_data)
    self.assertDictEqual(config_data, {})
    result = kwargs["custom"]
    self.assertIsInstance(result, CustomArgType)
    self.assertListEqual(result.value, [1, 2, "stuff"])
