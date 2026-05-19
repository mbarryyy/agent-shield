'use client';

import { useState, useEffect } from 'react';
import EpochDetailClient from '@/components/EpochDetailClient';

export default function EpochDetailShell() {
  const [epochId, setEpochId] = useState('');
  useEffect(() => {
    setEpochId(window.location.pathname.split('/')[2] ?? '');
  }, []);
  if (!epochId) return null;
  return <EpochDetailClient epochId={epochId} />;
}
