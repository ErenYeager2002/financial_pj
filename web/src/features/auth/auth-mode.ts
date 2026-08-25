export type AuthMode = 'session' | 'clerk' | 'hybrid';

export function authMode(): AuthMode {
  const value = process.env.FINANCIAL_AUTH_MODE?.trim().toLowerCase();
  return value === 'clerk' || value === 'hybrid' ? value : 'session';
}

export function clerkEnabled(mode: AuthMode = authMode()): boolean {
  return mode === 'clerk' || mode === 'hybrid';
}
