"""Tests for schema validator utilities."""

from __future__ import annotations

import json

from app.utils.schema_validator import get_schema_template, validate_json_schema


class TestSchemaValidator:
    """Test schema validator functions."""

    def test_validate_json_schema_valid(self):
        """Test validation of valid JSON schemas."""
        # Valid schema with all required fields
        valid_schema = json.dumps(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
            }
        )

        is_valid, error = validate_json_schema(valid_schema)
        assert is_valid is True
        assert error is None

    def test_validate_json_schema_invalid(self):
        """Test validation of invalid JSON schemas."""
        # Invalid: missing "properties" field
        invalid_schema_no_props = json.dumps(
            {
                "type": "object",
            }
        )

        is_valid, error = validate_json_schema(invalid_schema_no_props)
        assert is_valid is False
        assert "properties" in error

        # Invalid: wrong type (not object)
        invalid_schema_type = json.dumps(
            {
                "type": "string",
            }
        )

        is_valid, error = validate_json_schema(invalid_schema_type)
        assert is_valid is False
        assert "type" in error.lower() or "object" in error.lower()

        # Invalid: not valid JSON
        is_valid, error = validate_json_schema("not json {")
        assert is_valid is False
        assert "Invalid JSON" in error

    def test_validate_json_schema_empty(self):
        """Test validation of empty schema strings."""
        # Empty string should be valid (means free-form text generation)
        is_valid, error = validate_json_schema("")
        assert is_valid is True
        assert error is None

        # Whitespace only should be valid
        is_valid, error = validate_json_schema("   ")
        assert is_valid is True
        assert error is None

    def test_get_schema_template(self):
        """Test retrieval of preset schema templates."""
        # Test bank_transaction template
        template = get_schema_template("bank_transaction")
        assert template is not None
        schema_data = json.loads(template)
        assert "schema" in schema_data
        assert "properties" in schema_data["schema"]

        # Test invoice template
        template = get_schema_template("invoice")
        assert template is not None
        schema_data = json.loads(template)
        assert "schema" in schema_data

        # Test receipt template
        template = get_schema_template("receipt")
        assert template is not None
        schema_data = json.loads(template)
        assert "schema" in schema_data

    def test_get_schema_template_not_found(self):
        """Test that unknown template returns None."""
        template = get_schema_template("nonexistent_template")
        assert template is None

    def test_validate_json_schema_not_dict(self):
        """Test validation when JSON root is not a dict."""
        # JSON array is not valid
        is_valid, error = validate_json_schema("[1, 2, 3]")
        assert is_valid is False
        assert "object" in error.lower()
