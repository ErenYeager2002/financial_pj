'use client';
import { ClerkProvider } from '@clerk/nextjs';
import { zhCN } from '@clerk/localizations';
import { shadcn } from '@clerk/ui/themes';
import React from 'react';
import { ActiveThemeProvider } from '../themes/active-theme';
import QueryProvider from './query-provider';

const clerkLocalization = {
  ...zhCN,
  formFieldInputPlaceholder__password: '请输入您的密码',
  formFieldInputPlaceholder__signUpPassword: '请设置您的密码',
  signIn: {
    ...zhCN.signIn,
    start: {
      ...zhCN.signIn?.start,
      title: '登录企业管理后台',
      titleCombined: '登录企业管理后台'
    }
  },
  signUp: {
    ...zhCN.signUp,
    start: {
      ...zhCN.signUp?.start,
      subtitle: '创建账号后即可使用企业管理后台',
      subtitleCombined: '创建账号后即可使用企业管理后台'
    }
  }
};

export default function Providers({
  activeThemeValue,
  children
}: {
  activeThemeValue: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <ActiveThemeProvider initialTheme={activeThemeValue}>
        <ClerkProvider
          localization={clerkLocalization}
          appearance={{
            theme: shadcn,
            elements: {
              footerItem: 'hidden'
            },
            variables: {
              colorPrimary: 'var(--primary)',
              colorPrimaryForeground: 'var(--primary-foreground)',
              colorDanger: 'var(--destructive)',
              colorBackground: 'var(--card)',
              colorForeground: 'var(--foreground)',
              colorMuted: 'var(--muted)',
              colorMutedForeground: 'var(--muted-foreground)',
              colorInput: 'var(--input)',
              colorInputForeground: 'var(--foreground)',
              colorBorder: 'var(--border)',
              colorRing: 'var(--ring)',
              fontFamily: 'var(--font-sans)'
            }
          }}
        >
          <QueryProvider>{children}</QueryProvider>
        </ClerkProvider>
      </ActiveThemeProvider>
    </>
  );
}
