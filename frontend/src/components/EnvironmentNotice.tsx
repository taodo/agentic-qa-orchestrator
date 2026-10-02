export function EnvironmentNotice({ mode = import.meta.env.PUBLIC_QA_SENTINEL_MODE }: { mode?: string }) {
  const preview = mode === 'preview-demo';
  return <span className="environment" role={preview ? 'status' : undefined}
    title={preview ? 'Deterministic demo only. No live AI, source mutation or real test execution.' : undefined}>
    {preview ? 'DEMO PREVIEW · Synthetic' : 'Local operator workspace'}
  </span>;
}
