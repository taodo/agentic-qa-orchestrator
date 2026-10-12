import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { ThemeControl, THEME_KEY, readTheme } from './ThemeControl';
afterEach(()=>{ cleanup(); localStorage.clear(); delete document.documentElement.dataset.theme; vi.restoreAllMocks(); });
it.each([null,'invalid','system','DARK'])('falls back to dark for %s',value=>{
  localStorage.clear(); if(value) localStorage.setItem(THEME_KEY,value);
  render(<ThemeControl/>);expect(document.documentElement.dataset.theme).toBe('dark');
  expect(screen.getByRole('button',{name:/Dark/})).toHaveAttribute('aria-pressed','true');
});
it('persists light across unmount/remount without touching unrelated state',()=>{
  localStorage.setItem('unrelated','preserved');const view=render(<ThemeControl/>);
  fireEvent.click(screen.getByRole('button',{name:/Light/}));expect(localStorage.getItem(THEME_KEY)).toBe('light');
  expect(document.documentElement.dataset.theme).toBe('light');view.unmount();render(<ThemeControl/>);
  expect(screen.getByRole('button',{name:/Light/})).toHaveAttribute('aria-pressed','true');
  expect(localStorage.getItem('unrelated')).toBe('preserved');expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:/Dark/}));expect(localStorage.getItem(THEME_KEY)).toBe('dark');
});
it('works with unavailable storage',()=>{
  vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('Unavailable');});
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('Unavailable');});
  expect(readTheme()).toBe('dark');render(<ThemeControl/>);
  fireEvent.click(screen.getByRole('button',{name:/Light/}));expect(document.documentElement.dataset.theme).toBe('light');
});
it('sets the persisted theme before the application bootstrap and falls back safely',()=>{
  const html=readFileSync('index.html','utf8');
  const script=readFileSync('public/assets/theme-init.js','utf8');
  expect(html.indexOf('/assets/theme-init.js')).toBeLessThan(html.indexOf('/src/main.tsx'));
  localStorage.setItem(THEME_KEY,'light');new Function(script)();expect(document.documentElement.dataset.theme).toBe('light');
  localStorage.setItem(THEME_KEY,'invalid');new Function(script)();expect(document.documentElement.dataset.theme).toBe('dark');
});
