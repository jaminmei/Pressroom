import React from 'react';
import { WorkspaceCapability } from '@/types/workspace';
import { usePermission } from '@/hooks/usePermission';

export interface PermissionGateProps {
  capability: WorkspaceCapability;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export function PermissionGate({ capability, fallback, children }: PermissionGateProps) {
  const { can } = usePermission();

  if (can(capability)) {
    return <>{children}</>;
  }

  return <>{fallback ?? null}</>;
}
