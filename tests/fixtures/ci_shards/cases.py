"""Synthetic cases explicitly collected only by the shard integration test."""
import os
import unittest
import pytest


@pytest.mark.parametrize('value', range(6))
def test_parameterized(value):
    assert value >= 0


@pytest.fixture
def unavailable():
    pytest.skip('fixture-only allowed skip')


def test_fixture_skip(unavailable):
    raise AssertionError('setup skip should prevent the call')


class Example(unittest.TestCase):
    def test_class_method(self):
        self.assertFalse(os.environ.get('CI_SHARD_FIXTURE_FAIL'))
