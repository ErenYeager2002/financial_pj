'use client';
import React from 'react';
import { ActiveThemeProvider } from '../themes/active-theme';
import QueryProvider from './query-provider';
import { MaintenanceNotice } from './maintenance-notice';
export default function Providers({ activeThemeValue, children }: {
  activeThemeValue: string;
  children: React.ReactNode;
}) {
  return <ActiveThemeProvider initialTheme={activeThemeValue}><QueryProvider><MaintenanceNotice />{children}</QueryProvider></ActiveThemeProvider>;
}
