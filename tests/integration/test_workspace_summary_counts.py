from __future__ import annotations

from sqlalchemy import text

from tests.integration.workspace_api_support import WorkspaceApiHarness, create_workspace


def test_workspace_list_returns_scoped_summary_counts(
    workspace_api_harness: WorkspaceApiHarness,
) -> None:
    owner = workspace_api_harness.register_user("counts@example.com", "Counts")
    populated_id = create_workspace(owner.client, name="Populated")
    empty_id = create_workspace(owner.client, name="Empty")
    with workspace_api_harness.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO workflows "
                "(id, workflow_key, name, workspace_id, current_definition_json, latest_version) "
                "VALUES ('wf_summary', 'wk_summary', 'Summary', :workspace_id, '{}', 1)"
            ),
            {"workspace_id": populated_id},
        )
        session.execute(
            text(
                "INSERT INTO test_sets (id, name, workspace_id, document_count) "
                "VALUES ('db_summary', 'Summary', :workspace_id, 0)"
            ),
            {"workspace_id": populated_id},
        )
        session.commit()

    response = owner.client.get("/api/workspaces")

    assert response.status_code == 200
    summaries = {summary["id"]: summary for summary in response.json()["items"]}
    assert summaries[populated_id]["workflow_count"] == 1
    assert summaries[populated_id]["database_count"] == 1
    assert summaries[empty_id]["workflow_count"] == 0
    assert summaries[empty_id]["database_count"] == 0
