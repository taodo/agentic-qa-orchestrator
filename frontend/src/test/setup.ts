import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Unmocked fetch is forbidden'))));
  // Also deny browser network transports; jsdom does not load external resources.
  vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(() => { throw new Error('XHR is forbidden in tests'); });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
