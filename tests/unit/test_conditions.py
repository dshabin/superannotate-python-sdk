from unittest import TestCase

from src.superannotate.lib.core.conditions import Condition
from src.superannotate.lib.core.conditions import CONDITION_EQ
from src.superannotate.lib.core.conditions import CONDITION_GE


class TestCondition(TestCase):
    def test_query_build(self):
        condition = Condition("created", "today", CONDITION_GE)
        self.assertEquals(condition.build_query(), "created>=today")

    def test_multiple_condition_query_build(self):
        condition = Condition("id", 1, CONDITION_EQ) | Condition("id", 2, CONDITION_GE)
        self.assertEquals(condition.build_query(), "id=1|id>=2")
