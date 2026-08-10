from __future__ import annotations

from app.services.node_registry import NodeRegistryService


def test_end_final_node_registry_contract() -> None:
    registry = NodeRegistryService().get_registry()
    nodes_by_type = {node.node_type: node for node in registry.nodes}

    end_final = nodes_by_type["end/final"]
    engine_text = nodes_by_type["engine/text"]

    end_port = next(p for p in end_final.input_ports if p.name == "input")
    assert end_port.accepted_types == [
        "application/x-adaptor-output",
        "text/raw",
        "text/plain",
        "text/markdown",
        "image/*",
        "application/x-iteration-output",
    ]
    assert end_final.output_types == []
    assert end_final.max_outputs == 0
    assert end_final.max_inputs == -1

    assert engine_text.output_types == ["text/raw"]
