import AgentDetailShell from './client';

export async function generateStaticParams() {
  return [{ agent_id: 'detail' }];
}

export default function AgentDetailPage() {
  return <AgentDetailShell />;
}
