import type { ErrorView, GateEvaluationView, InvocationView, TestRunView } from '../api/types';

type Tone = 'neutral' | 'active' | 'success' | 'danger' | 'warning';
function Badge({ value, tone }: { value: string; tone: Tone }) {
  return <span className={`badge ${tone}`}>{value}</span>;
}
export function InvocationStatus({ value }: { value: InvocationView['status'] }) {
  const tones: Record<InvocationView['status'], Tone> = { STARTED: 'active', COMPLETED: 'success', FAILED: 'danger', BLOCKED: 'warning' };
  return <Badge value={value} tone={tones[value]} />;
}
export function TestOutcome({ value }: { value: TestRunView['outcome'] }) {
  const tones: Record<TestRunView['outcome'], Tone> = { PASS: 'success', FAIL: 'danger', UNKNOWN: 'neutral' };
  return <Badge value={value} tone={tones[value]} />;
}
export function TestExecutionStatus({ value }: { value: TestRunView['execution_status'] }) {
  const tones: Record<TestRunView['execution_status'], Tone> = { COMPLETED: 'success', INCOMPLETE: 'warning', FAILED: 'danger' };
  return <Badge value={value} tone={tones[value]} />;
}
export function GateResult({ value }: { value: GateEvaluationView['result'] }) {
  const tones: Record<GateEvaluationView['result'], Tone> = { PASS: 'success', FAIL: 'danger', BLOCKED: 'warning' };
  return <Badge value={value} tone={tones[value]} />;
}
export function ErrorSeverity({ value }: { value: ErrorView['severity'] }) {
  const tones: Record<ErrorView['severity'], Tone> = { INFO: 'neutral', WARNING: 'warning', ERROR: 'danger', CRITICAL: 'danger' };
  return <Badge value={value} tone={tones[value]} />;
}
