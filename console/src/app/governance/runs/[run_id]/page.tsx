import GovernanceRunShell from './client';

export async function generateStaticParams() {
  return [{ run_id: 'detail' }];
}

export default function GovernanceRunPage() {
  return <GovernanceRunShell />;
}
