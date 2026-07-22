
import { Drawer, Table } from 'antd';
import { useTranslation } from 'react-i18next';
import { ALL_CAPABILITIES, CAPABILITY_MATRIX, WORKSPACE_ROLES, CapabilityDescriptor } from '@/types/workspace';

export interface CapabilityMatrixDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function CapabilityMatrixDrawer({ open, onClose }: CapabilityMatrixDrawerProps) {
  const { t } = useTranslation('workspaces');
  const capabilities: CapabilityDescriptor[] = ALL_CAPABILITIES.map(cap => ({
    capability: cap,
    label: cap,
    description: cap,
    allowedRoles: CAPABILITY_MATRIX[cap],
  }));

  const columns = [
    {
      title: t('capability'),
      dataIndex: 'capability',
      key: 'capability',
      render: (text: string) => <code>{text}</code>
    },
    ...WORKSPACE_ROLES.map(role => ({
      title: t(role.role, { defaultValue: role.label }),
      key: role.role,
        render: (_: unknown, record: CapabilityDescriptor) => {
        return record.allowedRoles.includes(role.role) ? '✅' : '❌';
      }
    }))
  ];

  return (
    <Drawer
      title={t('capabilityMatrix')}
      placement="right"
      width={800}
      onClose={onClose}
      open={open}
      data-testid="capability-matrix-drawer"
    >
      <Table
        dataSource={capabilities}
        columns={columns}
        rowKey="capability"
        pagination={false}
        size="small"
      />
    </Drawer>
  );
}
