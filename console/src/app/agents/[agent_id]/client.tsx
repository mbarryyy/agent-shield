'use client';

import { useState, useEffect } from 'react';
import AgentDetailClient from '@/components/AgentDetailClient';

export default function AgentDetailShell() {
  const [agentId, setAgentId] = useState('');
  useEffect(() => {
    setAgentId(window.location.pathname.split('/')[2] ?? '');
  }, []);
  if (!agentId) return null;
  return <AgentDetailClient agentId={agentId} />;
}
