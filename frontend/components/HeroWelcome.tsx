import React from 'react';
import { SearchIcon, GitCompareIcon, UserCheckIcon } from './Icons.tsx';

interface HeroWelcomeProps {
  onPromptClick: (prompt: string) => void;
}

export const HeroWelcome: React.FC<HeroWelcomeProps> = ({ onPromptClick }) => {
  const cards = [
    {
      icon: SearchIcon,
      title: 'Discover trials near me',
      description: 'Find active clinical trials based on condition, location, and phase.',
      prompt: 'Find diabetes trials near Baltimore',
      color: 'from-blue-500 to-cyan-400'
    },
    {
      icon: GitCompareIcon,
      title: 'Compare clinical trials',
      description: 'Analyze differences in protocols, eligibility, and endpoints.',
      prompt: 'Compare two clinical trials',
      color: 'from-indigo-500 to-blue-500'
    },
    {
      icon: UserCheckIcon,
      title: 'Check patient alignment',
      description: 'Cross-reference patient profiles with inclusion/exclusion criteria.',
      prompt: 'Check preliminary patient-trial alignment',
      color: 'from-teal-500 to-emerald-400'
    }
  ];

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 text-center animate-fade-in max-w-4xl mx-auto w-full h-full min-h-[60vh]">
      <div className="mb-10">
        <div className="inline-flex items-center justify-center p-3 bg-blue-50 dark:bg-blue-900/20 rounded-2xl mb-6 shadow-sm">
          <SearchIcon className="w-8 h-8 text-blue-500 dark:text-blue-400" />
        </div>
        <h2 className="text-3xl md:text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-slate-900 to-slate-600 dark:from-white dark:to-slate-300 mb-4 tracking-tight">
          Find the right clinical trial <br className="hidden sm:block" /> information faster
        </h2>
        <p className="text-slate-500 dark:text-slate-400 max-w-xl mx-auto text-lg">
          TrialScout AI helps you discover trials, compare studies, screen preliminary patient alignment, and explain research concepts.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full mt-4">
        {cards.map((card, idx) => (
          <button
            key={idx}
            onClick={() => onPromptClick(card.prompt)}
            className="relative overflow-hidden flex flex-col items-start text-left p-6 bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-2xl hover:shadow-xl hover:-translate-y-1 hover:border-blue-300 dark:hover:border-blue-500/50 transition-all duration-300 group"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-blue-500/0 to-teal-500/0 group-hover:from-blue-500/5 dark:group-hover:from-blue-500/10 group-hover:to-teal-500/5 dark:group-hover:to-teal-500/10 transition-colors duration-300" />
            <div className={`relative p-3 rounded-xl bg-gradient-to-br ${card.color} text-white mb-5 shadow-sm group-hover:scale-110 transition-transform duration-300`}>
              <card.icon className="w-5 h-5" />
            </div>
            <h3 className="relative font-semibold text-slate-900 dark:text-white mb-2">{card.title}</h3>
            <p className="relative text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
              {card.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
};