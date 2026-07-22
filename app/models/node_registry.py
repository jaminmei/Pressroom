from __future__ import annotations

from pydantic import BaseModel, Field


class NodeCategory(BaseModel):
    category_id: str
    display_name: str
    description: str


class InputPortDef(BaseModel):
    name: str
    accepted_types: list[str] = Field(default_factory=list)
    required: bool = True
    max_connections: int = 1


class NodeDefinition(BaseModel):
    node_type: str
    display_name: str
    category: str
    description: str
    config_schema: dict[str, object] = Field(default_factory=dict)
    input_types: list[str] = Field(default_factory=list)  # deprecated, use input_ports
    output_types: list[str] = Field(default_factory=list)
    input_ports: list[InputPortDef] = Field(default_factory=list)
    max_inputs: int = -1
    max_outputs: int = -1
    requires_user_input: bool = False


class ConnectionRule(BaseModel):
    """Deprecated: category-based connection rules are replaced by port-type-based
    validation (MIME type matching on input_types/output_types). Retained for API
    backward compatibility — connection_rules always returns []. See spec §5."""

    from_category: str
    to_categories: list[str]


class NodeRegistry(BaseModel):
    version: str = "1.0.0"
    categories: list[NodeCategory] = Field(default_factory=list)
    nodes: list[NodeDefinition] = Field(default_factory=list)
    connection_rules: list[ConnectionRule] = Field(default_factory=list)
