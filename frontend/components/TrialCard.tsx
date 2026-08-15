import React from 'react';
import { TrialData } from '../types.ts';
import { MapPinIcon, BuildingIcon, ActivityIcon, ExternalLinkIcon } from './Icons.tsx';

interface TrialCardProps {
  trial: TrialData;
}

export const TrialCard: React.FC<TrialCardProps> = ({ trial }) => {
  const getStatusColor = (status: string) => {
    const s = status.toLowerCase();
    if (s.includes('recruiting') && !s.includes('not')) return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20';
    if (s.includes('active') || s.includes('enrolling')) return 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20';
    if (s.includes('completed')) return 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-700/50 dark:text-slate-300 dark:border-slate-600';
    return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20';
  };

  return (
    <div className="bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden my-3 hover:shadow-xl hover:-translate-y-1 hover:border-blue-300 dark:hover:border-blue-500/50 transition-all duration-300 group">
      <div className="p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row justify-between items-start gap-3 mb-4">
          <h3 className="text-base font-semibold text-slate-900 dark:text-white leading-snug group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
            {trial.title}
          </h3>
          <div className="flex flex-wrap gap-2 shrink-0">
            <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(trial.status)}`}>
              {trial.status}
            </span>
            <span className="px-2.5 py-1 rounded-full text-xs font-medium border bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-400 dark:border-indigo-500/20">
              {trial.phase}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-3 gap-x-4 mb-4 text-sm">
          <div className="flex items-start gap-2 text-slate-600 dark:text-slate-300">
            <ActivityIcon className="w-4 h-4 text-slate-400 dark:text-slate-500 shrink-0 mt-0.5" />
            <div>
              <span className="font-medium text-slate-700 dark:text-slate-200 block mb-0.5">Condition</span>
              <span className="line-clamp-1" title={trial.condition}>{trial.condition}</span>
            </div>
          </div>
          <div className="flex items-start gap-2 text-slate-600 dark:text-slate-300">
            <BuildingIcon className="w-4 h-4 text-slate-400 dark:text-slate-500 shrink-0 mt-0.5" />
            <div>
              <span className="font-medium text-slate-700 dark:text-slate-200 block mb-0.5">Sponsor</span>
              <span className="line-clamp-1" title={trial.sponsor}>{trial.sponsor}</span>
            </div>
          </div>
          <div className="flex items-start gap-2 text-slate-600 dark:text-slate-300 sm:col-span-2">
            <MapPinIcon className="w-4 h-4 text-slate-400 dark:text-slate-500 shrink-0 mt-0.5" />
            <div className="flex-1 flex justify-between items-center gap-2">
              <div>
                <span className="font-medium text-slate-700 dark:text-slate-200 block mb-0.5">Location</span>
                <span className="line-clamp-1" title={trial.location}>{trial.location}</span>
              </div>
              {trial.distance && (
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-700 px-2 py-1 rounded-md shrink-0">
                  {trial.distance}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="bg-slate-50 dark:bg-slate-900/50 rounded-xl p-3.5 mb-4 border border-slate-100 dark:border-slate-700/50">
          <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-3">
            {trial.summary}
          </p>
        </div>

        <div className="flex items-center justify-between pt-3 border-t border-slate-100 dark:border-slate-700">
          <span className="text-xs font-mono text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700">
            {trial.nctId}
          </span>
          <a
            href={trial.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors"
          >
            View on ClinicalTrials.gov
            <ExternalLinkIcon className="w-4 h-4" />
          </a>
        </div>
      </div>
    </div>
  );
};