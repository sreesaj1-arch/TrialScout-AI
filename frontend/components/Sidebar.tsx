import React from 'react';

import {
  PlusIcon,
  SearchIcon,
  GitCompareIcon,
  UserCheckIcon,
  XIcon
} from './Icons.tsx';


interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onPromptClick: (prompt: string) => void;
}


export const Sidebar:
  React.FC<SidebarProps> = ({
    isOpen,
    onClose,
    onNewChat,
    onPromptClick
  }) => {

    /*
     * ========================================================
     * Quick actions
     * ========================================================
     *
     * These are intentionally conversational rather than
     * incomplete prompts such as:
     *
     * "Find clinical trials for "
     *
     * This allows the real TrialScout agent to ask the user
     * for the information it needs.
     */

    const navItems = [

      {
        icon: SearchIcon,

        label: 'Discover Trials',

        description:
          'Search live clinical trial data',

        prompt:
          'I want to discover clinical trials. Please ask me for the condition, location, and any other information you need.'
      },

      {
        icon: GitCompareIcon,

        label: 'Compare Trials',

        description:
          'Compare known clinical studies',

        prompt:
          'I want to compare clinical trials. Please ask me for the NCT IDs or trial information you need.'
      },

      {
        icon: UserCheckIcon,

        label: 'Patient Alignment',

        description:
          'Review preliminary alignment',

        prompt:
          'I want to check preliminary patient-trial alignment. Please ask me for the patient information and trial NCT ID or IDs you need.'
      }

    ];


    return (

      <>

        {/* ===================================================
            Mobile overlay
        =================================================== */}

        {
          isOpen && (

            <div

              className="
                fixed
                inset-0
                bg-slate-900/50
                dark:bg-slate-950/80
                z-40
                md:hidden
                backdrop-blur-sm
                transition-opacity
              "

              onClick={
                onClose
              }

            />

          )
        }


        {/* ===================================================
            Sidebar
        =================================================== */}

        <aside

          className={`
            fixed
            inset-y-0
            left-0
            z-50
            w-72

            bg-white
            dark:bg-slate-900

            border-r
            border-slate-200
            dark:border-slate-800

            transform
            transition-transform
            duration-300
            ease-in-out

            flex
            flex-col

            ${
              isOpen
                ? 'translate-x-0'
                : '-translate-x-full'
            }

            md:relative
            md:translate-x-0
          `}

        >


          {/* =================================================
              Mobile menu header
          ================================================= */}

          <div
            className="
              p-4
              flex
              items-center
              justify-between
              md:hidden
              border-b
              border-slate-200
              dark:border-slate-800
            "
          >

            <span
              className="
                font-semibold
                text-slate-900
                dark:text-white
              "
            >
              Menu
            </span>


            <button

              onClick={
                onClose
              }

              className="
                p-2
                text-slate-500
                dark:text-slate-400
                hover:bg-slate-100
                dark:hover:bg-slate-800
                rounded-lg
                transition-colors
              "

              aria-label="Close sidebar"

            >

              <XIcon
                className="w-5 h-5"
              />

            </button>

          </div>


          {/* =================================================
              New Chat
          ================================================= */}

          <div
            className="
              p-4
              pb-3
            "
          >

            <button

              onClick={() => {

                onNewChat();
                onClose();

              }}

              className="
                w-full
                flex
                items-center
                gap-2

                px-4
                py-3

                bg-slate-900
                hover:bg-slate-800

                dark:bg-white
                dark:hover:bg-slate-100

                text-white
                dark:text-slate-900

                rounded-xl
                font-medium

                transition-all
                duration-200

                hover:shadow-md
                hover:-translate-y-0.5
              "

            >

              <PlusIcon
                className="w-5 h-5"
              />

              New Chat

            </button>

          </div>


          {/* =================================================
              Sidebar content
          ================================================= */}

          <div
            className="
              flex-1
              overflow-y-auto
              py-2
              px-3
            "
          >


            {/* ===============================================
                Quick Actions
            =============================================== */}

            <div
              className="mb-7"
            >

              <h3
                className="
                  px-3
                  mb-2

                  text-[11px]
                  font-semibold

                  text-slate-500
                  dark:text-slate-400

                  uppercase
                  tracking-wider
                "
              >
                Quick Actions
              </h3>


              <div
                className="
                  space-y-1.5
                "
              >

                {
                  navItems.map(
                    (
                      item,
                      idx
                    ) => (

                      <button

                        key={
                          idx
                        }

                        onClick={() => {

                          onPromptClick(
                            item.prompt
                          );

                          onClose();

                        }}

                        className="
                          group

                          w-full
                          flex
                          items-start
                          gap-3

                          px-3
                          py-3

                          text-left

                          hover:bg-slate-100
                          dark:hover:bg-slate-800/80

                          rounded-xl

                          transition-all
                          duration-200

                          hover:translate-x-1
                        "

                      >

                        {/* Icon */}

                        <div
                          className="
                            mt-0.5

                            w-8
                            h-8

                            flex
                            items-center
                            justify-center

                            rounded-lg

                            bg-slate-100
                            dark:bg-slate-800

                            group-hover:bg-blue-50
                            dark:group-hover:bg-blue-500/10

                            transition-colors
                          "
                        >

                          <item.icon
                            className="
                              w-4
                              h-4

                              text-slate-500
                              dark:text-slate-400

                              group-hover:text-blue-600
                              dark:group-hover:text-blue-400

                              transition-colors
                            "
                          />

                        </div>


                        {/* Label */}

                        <div
                          className="
                            min-w-0
                            flex-1
                          "
                        >

                          <div
                            className="
                              text-sm
                              font-medium

                              text-slate-700
                              dark:text-slate-200

                              group-hover:text-slate-900
                              dark:group-hover:text-white
                            "
                          >
                            {item.label}
                          </div>


                          <div
                            className="
                              mt-0.5

                              text-[11px]
                              leading-4

                              text-slate-400
                              dark:text-slate-500
                            "
                          >
                            {item.description}
                          </div>

                        </div>

                      </button>

                    )
                  )
                }

              </div>

            </div>


            {/* ===============================================
                Session information
            ===============================================
                
                Replaces the fake App Builder "Recent Sessions"
                data.

                This describes real behavior in our frontend:
                Agent Runtime conversation context is retained
                until New Chat clears the session.
            */}

            <div
              className="
                px-3
                mb-6
              "
            >

              <h3
                className="
                  mb-3

                  text-[11px]
                  font-semibold

                  text-slate-500
                  dark:text-slate-400

                  uppercase
                  tracking-wider
                "
              >
                Current Session
              </h3>


              <div
                className="
                  relative
                  overflow-hidden

                  p-3.5

                  rounded-xl

                  bg-slate-50
                  dark:bg-slate-800/40

                  border
                  border-slate-200
                  dark:border-slate-700/70
                "
              >

                {/* Subtle accent */}

                <div
                  className="
                    absolute
                    left-0
                    top-0
                    bottom-0
                    w-0.5

                    bg-gradient-to-b
                    from-blue-500
                    to-teal-400
                  "
                />


                <div
                  className="
                    flex
                    items-center
                    gap-2
                    mb-2
                  "
                >

                  <span
                    className="
                      relative
                      flex
                      h-2
                      w-2
                    "
                  >

                    <span
                      className="
                        animate-ping
                        absolute
                        inline-flex
                        h-full
                        w-full
                        rounded-full
                        bg-emerald-400
                        opacity-50
                      "
                    />

                    <span
                      className="
                        relative
                        inline-flex
                        rounded-full
                        h-2
                        w-2
                        bg-emerald-500
                      "
                    />

                  </span>


                  <span
                    className="
                      text-xs
                      font-medium

                      text-slate-700
                      dark:text-slate-300
                    "
                  >
                    Conversation context active
                  </span>

                </div>


                <p
                  className="
                    text-[11px]
                    leading-5

                    text-slate-500
                    dark:text-slate-400
                  "
                >
                  TrialScout remembers context within this conversation.
                  Select New Chat to begin a fresh session.
                </p>

              </div>

            </div>


          </div>


          {/* =================================================
              Sidebar footer
          ================================================= */}

          <div
            className="
              px-5
              py-4

              border-t
              border-slate-200
              dark:border-slate-800
            "
          >

            <div
              className="
                flex
                items-center
                gap-2
              "
            >

              <div
                className="
                  w-1.5
                  h-1.5
                  rounded-full
                  bg-emerald-500
                "
              />


              <span
                className="
                  text-[10px]
                  uppercase
                  tracking-wider
                  font-medium

                  text-slate-400
                  dark:text-slate-500
                "
              >
                TrialScout AI
              </span>

            </div>

          </div>


        </aside>

      </>

    );

  };