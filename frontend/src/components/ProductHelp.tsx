import { useId, useState } from 'react';

export function ProductHelp() {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  return <section className="panel product-help" aria-label="Product help">
    <button type="button" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(value => !value)}>
      How QA Sentinel works
    </button>
    <div id={contentId} hidden={!open}>
      <p>QA Sentinel coordinates QA work through agents, deterministic tools and inspectable evidence.</p>
      <dl>
        <dt>Project</dt><dd>The software identity that owns your Tasks. Creating a Project does not configure a workspace or runtime.</dd>
        <dt>Task</dt><dd>One QA requirement within a Project. Open the Project to create a Task, then open the Task to inspect it.</dd>
        <dt>Run</dt><dd>Creates a durable execution request for the configured workflow. You can leave or refresh and recover its status. Task state and evidence determine the outcome. Resume only restores a blocked Task's stored state; click Run separately afterward.</dd>
        <dt>Evidence</dt><dd>After Run, inspect Overview and Timeline, then Artifacts, Invocations, Test Runs, Errors, Decisions and Gates. A safe stop may still produce evidence.</dd>
      </dl>
      <p>For the demo, open Demo Calculator and create a Task titled <strong>Division support</strong> with requirement <strong>Add division support and reject division by zero.</strong></p>
      <p className="notice">Demo evidence is deterministic and synthetic: no live AI, source writes or real test execution. Other Projects remain runtime-unconfigured in demo mode.</p>
    </div>
  </section>;
}
