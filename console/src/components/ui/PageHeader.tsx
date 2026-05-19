import Link from 'next/link';

interface Breadcrumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumbs?: Breadcrumb[];
  actions?: React.ReactNode;
}

export default function PageHeader({ title, subtitle, breadcrumbs, actions }: PageHeaderProps) {
  return (
    <div className="mb-8">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav className="mb-3 flex items-center gap-2 flex-wrap overflow-hidden">
          {breadcrumbs.map((crumb, index) => (
            <span key={index} className="flex items-center gap-2 min-w-0">
              {index > 0 && (
                <span className="font-mono text-[11px] text-ink-dim shrink-0">/</span>
              )}
              {crumb.href ? (
                <Link
                  href={crumb.href}
                  className="font-mono text-[11px] uppercase tracking-wider text-ink-dim hover:text-ink transition-colors no-underline whitespace-nowrap"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span className="font-mono text-[11px] uppercase tracking-wider text-ink truncate">
                  {crumb.label}
                </span>
              )}
            </span>
          ))}
        </nav>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <h1 className="font-sans text-2xl font-semibold tracking-tight text-ink leading-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 font-mono text-[13px] text-ink-dim break-all">
              {subtitle}
            </p>
          )}
        </div>

        {actions && (
          <div className="flex items-center gap-3 shrink-0">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
