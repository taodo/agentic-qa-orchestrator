import { useId, useState } from 'react';

export function ProductHelp() {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  return <section className="panel product-help" aria-label="Product help">
    <button type="button" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(value => !value)}>How campaigns work</button>
    <div id={contentId} hidden={!open}>
      <p>Prepare QA work with structured requirements, test specifications and explicit human review.</p>
      <dl>
        <dt>Project</dt><dd>The software identity that owns your QA Campaigns. A repository is optional for campaign preparation.</dd>
        <dt>QA Campaign</dt><dd>One QA initiative. Create a Campaign inside a Project, then inspect its preparation views.</dd>
        <dt>Requirements and Test Specifications</dt><dd>Saved requirements carry source evidence. Imported and AI-generated test designs share explicit review status; neither is automatically approved.</dd>
        <dt>Traceability</dt><dd>Shows which requirements have approved linked tests and which have gaps. Coverage does not prove a test passed.</dd>
        <dt>Readiness</dt><dd>A derived assessment of preparation, approvals and coverage. Campaign Approved and readiness Ready remain separate.</dd>
      </dl>
      <p>These views read saved preparation data. Creating a Campaign does not upload a document, generate tests, approve content or start execution.</p>
      <p className="notice">Demo evidence remains deterministic and synthetic. An empty Campaign stays empty until content is prepared; the browser does not invent requirements or tests.</p>
      <p className="hint">Historical Task screens are available under Legacy workflows in a Project; Operations remains available separately.</p>
    </div>
  </section>;
}
