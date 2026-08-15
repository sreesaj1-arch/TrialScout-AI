import React, { useState, KeyboardEvent, useRef } from 'react';
import { SendIcon } from './Icons.tsx';

interface InputAreaProps {
  onSendMessage: (text: string) => void;
  disabled: boolean;
}

export const InputArea: React.FC<InputAreaProps> = ({ onSendMessage, disabled }) => {
  const [inputValue, setInputValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    if (inputValue.trim() && !disabled) {
      onSendMessage(inputValue.trim());
      setInputValue('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    // Auto-resize
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto px-4 pb-4 pt-2">
      <div className="relative flex items-end bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-2xl shadow-sm focus-within:ring-2 focus-within:ring-blue-500/50 focus-within:border-blue-500 dark:focus-within:border-blue-400 transition-all">
        <textarea
          ref={textareaRef}
          value={inputValue}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Ask about clinical trials, conditions, or specific NCT IDs..."
          className="w-full py-4 pl-5 pr-14 bg-transparent border-none focus:outline-none text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 disabled:opacity-50 resize-none max-h-[200px] min-h-[56px]"
          rows={1}
        />
        <button
          onClick={handleSend}
          disabled={disabled || !inputValue.trim()}
          className="absolute right-2 bottom-2 p-2.5 bg-gradient-to-r from-blue-600 to-teal-500 text-white rounded-xl hover:from-blue-500 hover:to-teal-400 hover:shadow-md hover:-translate-y-0.5 disabled:from-slate-200 disabled:to-slate-200 dark:disabled:from-slate-700 dark:disabled:to-slate-700 disabled:text-slate-400 dark:disabled:text-slate-500 disabled:hover:translate-y-0 disabled:hover:shadow-none transition-all duration-200 flex items-center justify-center group"
          aria-label="Send message"
        >
          <SendIcon className="w-5 h-5 group-hover:scale-110 transition-transform duration-200" />
        </button>
      </div>
    </div>
  );
};