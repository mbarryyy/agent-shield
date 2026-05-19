import EpochDetailShell from './client';

export async function generateStaticParams() {
  return [{ epoch_id: 'detail' }];
}

export default function EpochDetailPage() {
  return <EpochDetailShell />;
}
