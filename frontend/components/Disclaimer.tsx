import React from 'react';
import { ShieldAlertIcon } from './Icons.tsx';

export const Disclaimer: React.FC = () => {
  return (
    <div className="w-full py-3 px-4 text-center flex items-center justify-center gap-2 text-xs text-slate-500 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 backdrop-blur-sm">
      <ShieldAlertIcon className="w-4 h-4 text-slate-400 dark:text-slate-500 shrink-0" />
      <p className="max-w-3xl">
        TrialScout provides research and navigation support only. It does not determine medical eligibility or provide medical advice.
      </p>
    </div>
  );
};