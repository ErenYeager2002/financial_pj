import { useRegisterActions } from 'kbar';
import { useTheme } from 'next-themes';
import { useThemeConfig } from '@/components/themes/active-theme';
import { THEMES } from '@/components/themes/theme.config';

const useThemeSwitching = () => {
  const { theme, setTheme } = useTheme();
  const { activeTheme, setActiveTheme } = useThemeConfig();

  const toggleDarkLight = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  };

  const cycleTheme = () => {
    const currentIndex = THEMES.findIndex((t) => t.value === activeTheme);
    const nextIndex = (currentIndex + 1) % THEMES.length;
    setActiveTheme(THEMES[nextIndex].value);
  };

  const themeActions = [
    {
      id: 'cycleTheme',
      name: '切换主题',
      shortcut: ['t', 't'],
      section: '主题',
      perform: cycleTheme
    },
    {
      id: 'toggleDarkLight',
      name: '切换深色或浅色模式',
      shortcut: ['d', 'd'],
      section: '主题',
      perform: toggleDarkLight
    },
    {
      id: 'setLightTheme',
      name: '使用浅色模式',
      section: '主题',
      perform: () => setTheme('light')
    },
    {
      id: 'setDarkTheme',
      name: '使用深色模式',
      section: '主题',
      perform: () => setTheme('dark')
    }
  ];

  useRegisterActions(themeActions, [theme, activeTheme]);
};

export default useThemeSwitching;
