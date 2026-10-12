import { useLayoutEffect, useState } from 'react';
export type Theme = 'dark' | 'light';
export const THEME_KEY = 'qa-sentinel.theme';
export function readTheme(): Theme {
  try { return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'; }
  catch { return 'dark'; }
}
export function ThemeControl() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useLayoutEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  function choose(value: Theme) {
    setTheme(value);
    try { localStorage.setItem(THEME_KEY, value); } catch { /* Session-local appearance still works. */ }
  }
  return <div className="theme-control" role="group" aria-label="Appearance">
    {(['light','dark'] as const).map(value => <button key={value} aria-pressed={theme === value} onClick={() => choose(value)}>{value === 'light' ? '☀ Light' : '☾ Dark'}</button>)}
  </div>;
}
