'use client';

import { useState, useEffect } from 'react';
import OperationDetailClient from '@/components/OperationDetailClient';

export default function OperationDetailShell() {
  const [operationId, setOperationId] = useState('');
  useEffect(() => {
    setOperationId(window.location.pathname.split('/')[2] ?? '');
  }, []);
  if (!operationId) return null;
  return <OperationDetailClient operationId={operationId} />;
}
