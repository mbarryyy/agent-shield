import OperationDetailShell from './client';

export async function generateStaticParams() {
  return [{ operation_id: 'detail' }];
}

export default function OperationDetailPage() {
  return <OperationDetailShell />;
}
