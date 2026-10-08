import type { ReactNode } from 'react';

export function PageHeader({ title, eyebrow, description, breadcrumb }: {
  title: string; eyebrow?: string; description?: string; breadcrumb?: ReactNode;
}) {
  return <header className="page-header">
    {breadcrumb && <div className="breadcrumb">{breadcrumb}</div>}
    {eyebrow && <p className="eyebrow">{eyebrow}</p>}
    <h1>{title}</h1>
    {description && <p className="page-description">{description}</p>}
  </header>;
}

export function SectionHeader({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="panel-heading"><h2>{title}</h2>{children && <div className="actions">{children}</div>}</div>;
}

export function Metric({ label, value }: { label: string; value: number }) {
  return <div className="metric"><dt>{label}</dt><dd>{value}</dd></div>;
}
