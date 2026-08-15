import React from 'react';
import {
  StethoscopeIcon,
  SunIcon,
  MoonIcon,
  MenuIcon
} from './Icons.tsx';

export type AgentStatus =
  | 'ready'
  | 'working'
  | 'connected'
  | 'error';

interface HeaderProps {
  isDarkMode: boolean;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  agentStatus: AgentStatus;
}

export const Header: React.FC<HeaderProps> = ({
  isDarkMode,
  toggleTheme,
  toggleSidebar,
  agentStatus
}) => {
  const getStatusConfig = () => {
    switch (agentStatus) {
      case 'working':
        return {
          label: 'Agent: Working...',
          dotClass: 'bg-amber-400',
          pingClass: 'bg-amber-400',
          containerClass:
            'bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20 text-amber-700 dark:text-amber-300'
        };

      case 'connected':
        return {
          label: 'Agent: Connected',
          dotClass: 'bg-emerald-500',
          pingClass: 'bg-emerald-400',
          containerClass:
            'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20 text-emerald-700 dark:text-emerald-300'
        };

      case 'error':
        return {
          label: 'Agent: Connection error',
          dotClass: 'bg-red-500',
          pingClass: 'bg-red-400',
          containerClass:
            'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20 text-red-700 dark:text-red-300'
        };

      case 'ready':
      default:
        return {
          label: 'Agent: Ready',
          dotClass: 'bg-blue-500',
          pingClass: 'bg-blue-400',
          containerClass:
            'bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-blue-500/20 text-blue-700 dark:text-blue-300'
        };
    }
  };

  const status = getStatusConfig();

  return (
    <header className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 sticky top-0 z-30 transition-colors duration-300">
      <div className="w-full px-4 h-16 flex items-center justify-between">

        <div className="flex items-center gap-3">
          <button
            onClick={toggleSidebar}
            className="p-2 -ml-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 md:hidden transition-colors"
            aria-label="Toggle sidebar"
          >
            <MenuIcon className="w-6 h-6" />
          </button>

          <div className="flex items-center gap-3">
            <div className="bg-gradient-to-br from-blue-500 to-teal-400 p-2 rounded-xl text-white shadow-sm">
              <StethoscopeIcon className="w-5 h-5" />
            </div>

            <div className="hidden sm:block">
              <h1 className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-slate-900 to-slate-600 dark:from-white dark:to-slate-300 leading-tight">
                TrialScout AI
              </h1>

              <p className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">
                Clinical Trial Intelligence
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">

          <div
            className={`hidden sm:flex items-center gap-1.5 px-3 py-1.5 border rounded-full text-xs font-medium transition-colors ${status.containerClass}`}
          >
            <span className="relative flex h-2 w-2">
              {(agentStatus === 'working' ||
                agentStatus === 'connected') && (
                <span
                  className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${status.pingClass}`}
                />
              )}

              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${status.dotClass}`}
              />
            </span>

            {status.label}
          </div>

          <button
            onClick={toggleTheme}
            className="p-2 rounded-full text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            aria-label="Toggle theme"
          >
            {isDarkMode ? (
              <SunIcon className="w-5 h-5" />
            ) : (
              <MoonIcon className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>
    </header>
  );
};