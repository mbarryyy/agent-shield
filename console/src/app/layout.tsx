import type { Metadata } from 'next';
import './globals.css';
import AppShell from '@/components/AppShell';
import I18nProvider from '@/components/I18nProvider';

export const metadata: Metadata = {
  title: 'Elydora Console',
  description: 'Enterprise AI accountability and compliance console',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-bg text-ink font-sans antialiased">
        <I18nProvider>
          <AppShell>{children}</AppShell>
        </I18nProvider>
      </body>
    </html>
  );
}
