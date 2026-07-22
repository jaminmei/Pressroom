from app.services.workflow_migrator import migrate_workflow


class TestWorkflowMigration:
    """Tests for engine/vlm -> engine/model migration."""

    def test_vlm_node_type_replaced(self):
        """engine/vlm node_type becomes engine/model."""
        old_workflow = {
            "nodes": [
                {"id": "n1", "type": "input/image", "config": {}},
                {"id": "n2", "type": "engine/vlm", "config": {"model": "gpt-4.1"}},
                {"id": "n3", "type": "end/final", "config": {}},
                {"id": "n4", "type": "end/final", "config": {}},
            ],
            "edges": [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
                {"source": "n3", "target": "n4"},
            ],
        }
        migrated = migrate_workflow(old_workflow)
        node_types = [n["type"] for n in migrated["nodes"]]
        assert "engine/vlm" not in node_types
        assert "engine/model" in node_types

    def test_vlm_config_preserved(self):
        """VLM node config (model, prompt, temperature) is preserved after migration."""
        old_workflow = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "engine/vlm",
                    "config": {
                        "model": "gpt-4.1",
                        "prompt": "Extract text",
                        "temperature": 0.1,
                    },
                },
            ],
            "edges": [],
        }
        migrated = migrate_workflow(old_workflow)
        model_node = migrated["nodes"][0]
        assert model_node["type"] == "engine/model"
        assert model_node["config"]["model"] == "gpt-4.1"
        assert model_node["config"]["prompt"] == "Extract text"
        assert model_node["config"]["temperature"] == 0.1

    def test_edges_preserved(self):
        """Edge source/target references remain valid after migration."""
        old_workflow = {
            "nodes": [
                {"id": "n1", "type": "input/image", "config": {}},
                {"id": "n2", "type": "engine/vlm", "config": {}},
            ],
            "edges": [
                {"source": "n1", "target": "n2"},
            ],
        }
        migrated = migrate_workflow(old_workflow)
        assert migrated["edges"] == old_workflow["edges"]

    def test_no_vlm_noop(self):
        """Workflow without engine/vlm passes through unchanged."""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "input/image", "config": {}},
                {"id": "n2", "type": "engine/ocr", "config": {}},
            ],
            "edges": [
                {"source": "n1", "target": "n2"},
            ],
        }
        migrated = migrate_workflow(workflow)
        assert migrated is workflow  # Same object, not a copy

    def test_multiple_vlm_nodes_migrated(self):
        """All engine/vlm nodes in a workflow are migrated."""
        old_workflow = {
            "nodes": [
                {"id": "n1", "type": "engine/vlm", "config": {"model": "a"}},
                {"id": "n2", "type": "engine/vlm", "config": {"model": "b"}},
            ],
            "edges": [],
        }
        migrated = migrate_workflow(old_workflow)
        for node in migrated["nodes"]:
            assert node["type"] == "engine/model"

    def test_original_not_mutated(self):
        """migrate_workflow does not mutate the input dict."""
        old_workflow = {
            "nodes": [
                {"id": "n1", "type": "engine/vlm", "config": {"model": "test"}},
            ],
            "edges": [],
        }
        migrate_workflow(old_workflow)
        assert old_workflow["nodes"][0]["type"] == "engine/vlm"
