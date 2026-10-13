import type { QARun, BrowserPlanIdentity } from '../api/runTypes';

export function BrowserRunIdentity({run}:{run:QARun}) {
  const runtime = run.executor_kind === 'WEB_BROWSER' ? run.runtime_identity : null;
  return <dl className="metadata" aria-label="Stored executor identity">
    <div><dt>Executor</dt><dd>{run.executor_kind ?? 'Unavailable'}</dd></div>
    {run.executor_kind === 'WEB_BROWSER' && <>
      <div><dt>Runtime</dt><dd>{runtime ? `Playwright · ${runtime.engine === 'CHROMIUM' ? 'Chromium' : runtime.engine}` : 'Unavailable'}</dd></div>
      {runtime && <>
        <div><dt>Playwright version</dt><dd>{runtime.playwright_version}</dd></div>
        <div><dt>Chromium version</dt><dd>{runtime.browser_version}</dd></div>
        <div><dt>Chromium revision</dt><dd>{runtime.chromium_revision}</dd></div>
        <div><dt>Adapter version</dt><dd>{runtime.adapter_version}</dd></div>
      </>}
    </>}
  </dl>;
}

export function SealedBrowserPlanIdentity({plan}:{plan:BrowserPlanIdentity|null|undefined}) {
  return <section aria-label="Sealed browser plan identity"><h5>Sealed browser plan identity</h5>
    {!plan ? <p>Browser plan identity unavailable. No plan is inferred from evidence.</p> : <>
      <dl className="metadata"><div><dt>Plan origin</dt><dd>{plan.origin}</dd></div>
        <div><dt>Plan version</dt><dd>{plan.plan.version}</dd></div>
        <div><dt>Plan hash</dt><dd><code>{plan.plan_hash.slice(0,16)}…</code></dd></div></dl>
      <details><summary>Full plan hash</summary><code>{plan.plan_hash}</code></details>
    </>}
  </section>;
}
