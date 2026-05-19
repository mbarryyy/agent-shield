import type { AgentStatus, KeyStatus, ExportStatus } from '@elydora/shared';

type Status = AgentStatus | KeyStatus | ExportStatus | 'running' | 'queued' | 'done' | 'failed' | 'verified' | 'invalid';

interface StatusBadgeProps {
  status: Status;
  size?: 'sm' | 'md';
}

const statusConfig: Record<Status, { color: string; dotColor: string; label: string }> = {
  active: {
    color: 'text-ink',
    dotColor: 'bg-ink',
    label: 'Active',
  },
  frozen: {
    color: 'text-blue-600',
    dotColor: 'bg-blue-500',
    label: 'Frozen',
  },
  revoked: {
    color: 'text-red-600',
    dotColor: 'bg-red-500',
    label: 'Revoked',
  },
  retired: {
    color: 'text-ink-dim',
    dotColor: 'bg-ink-dim',
    label: 'Retired',
  },
  queued: {
    color: 'text-ink-dim',
    dotColor: 'bg-ink-dim',
    label: 'Queued',
  },
  running: {
    color: 'text-amber-600',
    dotColor: 'bg-amber-500',
    label: 'Running',
  },
  done: {
    color: 'text-green-600',
    dotColor: 'bg-green-500',
    label: 'Done',
  },
  failed: {
    color: 'text-red-600',
    dotColor: 'bg-red-500',
    label: 'Failed',
  },
  verified: {
    color: 'text-green-600',
    dotColor: 'bg-green-500',
    label: 'Verified',
  },
  invalid: {
    color: 'text-red-600',
    dotColor: 'bg-red-500',
    label: 'Invalid',
  },
};

export default function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const config = statusConfig[status] ?? {
    color: 'text-ink-dim',
    dotColor: 'bg-ink-dim',
    label: status,
  };

  const dotSize = size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2';
  const textSize = size === 'sm' ? 'text-[10px]' : 'text-[11px]';

  return (
    <span className={`inline-flex items-center gap-1.5 ${config.color}`}>
      <span
        className={`${dotSize} rounded-full ${config.dotColor} ${
          status === 'running' ? 'pulse-dot' : ''
        }`}
      />
      <span className={`font-mono ${textSize} font-medium uppercase tracking-wider`}>
        {config.label}
      </span>
    </span>
  );
}
