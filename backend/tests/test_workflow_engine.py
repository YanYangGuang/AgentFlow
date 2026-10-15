import unittest

from app.services.workflow_engine import validate_graph


def node(node_id: str, kind: str) -> dict:
    return {"id": node_id, "type": kind, "label": node_id, "config": {}}


class WorkflowGraphTests(unittest.TestCase):
    def test_multiple_inputs_and_outputs_are_valid_dag(self):
        nodes = [
            node("input_a", "input"), node("input_b", "input"),
            node("llm_a", "llm"), node("tool_b", "tool"),
            node("output_a", "output"), node("output_b", "output"),
        ]
        edges = [
            {"id": "e1", "source": "input_a", "target": "llm_a"},
            {"id": "e2", "source": "llm_a", "target": "output_a"},
            {"id": "e3", "source": "input_b", "target": "tool_b"},
            {"id": "e4", "source": "tool_b", "target": "output_b"},
        ]
        order, errors = validate_graph(nodes, edges)
        self.assertFalse(errors)
        self.assertEqual(len(order), len(nodes))

    def test_each_node_must_be_reachable_from_some_input(self):
        nodes = [node("input_a", "input"), node("input_b", "input"), node("output", "output")]
        edges = [{"id": "e1", "source": "input_a", "target": "output"}]
        _, errors = validate_graph(nodes, edges)
        self.assertTrue(any("input_b" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
