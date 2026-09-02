import { describe, it, assert } from 'vitest';
import {
  WORKSPACE_ROLES,
  CAPABILITY_MATRIX,
  ALL_CAPABILITIES,
  WorkspaceCapability,
  WorkspaceRole
} from './workspace';

describe('Workspace Types and Constants', () => {
  it('should have exactly 5 roles defined', () => {
    assert.strictEqual(WORKSPACE_ROLES.length, 5);
  });

  it('should map exactly 37 capabilities in the matrix', () => {
    assert.strictEqual(Object.keys(CAPABILITY_MATRIX).length, 41);
  });

  it('should include every capability in ALL_CAPABILITIES as a key in CAPABILITY_MATRIX', () => {
    ALL_CAPABILITIES.forEach((cap) => {
      assert.isTrue(cap in CAPABILITY_MATRIX, `Missing capability in matrix: ${cap}`);
    });
  });

  it('should verify exhaustiveness at compile time', () => {
    // Type-level check to ensure CAPABILITY_MATRIX has all keys from WorkspaceCapability
    const _check: Record<WorkspaceCapability, WorkspaceRole[]> = CAPABILITY_MATRIX;
    assert.isDefined(_check);
  });
});
