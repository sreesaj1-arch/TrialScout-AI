import React from 'react';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

import 'katex/dist/katex.min.css';

import {
  AgentDisplayInfo,
  ChatMessage
} from '../types.ts';

import {
  BotIcon,
  UserIcon
} from './Icons.tsx';

import {
  TrialCard
} from './TrialCard.tsx';


interface MessageBubbleProps {
  message: ChatMessage;
}


/*
 * ============================================================
 * Default agent
 * ============================================================
 */

const DEFAULT_AGENT:
  AgentDisplayInfo = {

    key:
      'orchestrator',

    label:
      'AI Agent',

    activity:
      'TrialScout is analyzing your request...'
  };


/*
 * ============================================================
 * Agent-specific visual styling
 * ============================================================
 */

const getAgentVisuals =
  (
    agent:
      AgentDisplayInfo
  ) => {

    switch (
      agent.key
    ) {

      case 'discovery':

        return {
          badge:
            'bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400',

          avatar:
            'from-blue-600 via-blue-500 to-cyan-400',

          glow:
            'from-blue-500 via-cyan-400 to-cyan-300',

          dot:
            'bg-blue-400'
        };


      case 'analysis':

        return {
          badge:
            'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400',

          avatar:
            'from-indigo-600 via-indigo-500 to-violet-400',

          glow:
            'from-indigo-500 via-violet-400 to-purple-400',

          dot:
            'bg-indigo-400'
        };


      case 'fhir_screening':

        return {
          badge:
            'bg-teal-50 text-teal-700 dark:bg-teal-500/10 dark:text-teal-400',

          avatar:
            'from-teal-600 via-teal-500 to-emerald-400',

          glow:
            'from-teal-500 via-emerald-400 to-cyan-400',

          dot:
            'bg-teal-400'
        };


      case 'matching_ranking':

        return {
          badge:
            'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400',

          avatar:
            'from-amber-500 via-orange-500 to-rose-400',

          glow:
            'from-amber-400 via-orange-400 to-rose-400',

          dot:
            'bg-amber-400'
        };


      case 'research_knowledge':

        return {
          badge:
            'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-400',

          avatar:
            'from-violet-600 via-purple-500 to-indigo-400',

          glow:
            'from-violet-500 via-purple-400 to-indigo-400',

          dot:
            'bg-violet-400'
        };


      case 'url_context':

        return {
          badge:
            'bg-cyan-50 text-cyan-700 dark:bg-cyan-500/10 dark:text-cyan-400',

          avatar:
            'from-cyan-600 via-sky-500 to-blue-400',

          glow:
            'from-cyan-400 via-sky-400 to-blue-400',

          dot:
            'bg-cyan-400'
        };


      case 'orchestrator':
      default:

        return {
          badge:
            'bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400',

          avatar:
            'from-blue-600 via-blue-500 to-teal-400',

          glow:
            'from-blue-500 via-cyan-400 to-teal-400',

          dot:
            'bg-emerald-500'
        };

    }

  };


/*
 * ============================================================
 * Small routing path component
 * ============================================================
 */

const AgentRoute:
  React.FC<{
    route?:
      AgentDisplayInfo[];
  }> = ({
    route
  }) => {

    if (
      !route ||
      route.length <= 1
    ) {
      return null;
    }


    return (

      <div
        className="
          flex
          flex-wrap
          items-center
          gap-1.5
          mb-2
          px-1

          text-[10px]
          font-medium
          text-slate-400
          dark:text-slate-500
        "
      >

        {
          route.map(
            (
              agent,
              index
            ) => (

              <React.Fragment
                key={
                  `${agent.key}-${index}`
                }
              >

                {
                  index > 0 && (

                    <span
                      className="
                        text-slate-300
                        dark:text-slate-600
                      "
                    >
                      →
                    </span>

                  )
                }


                <span>
                  {agent.label}
                </span>

              </React.Fragment>

            )
          )
        }

      </div>

    );

  };


/*
 * ============================================================
 * TrialScout message
 * ============================================================
 */

export const MessageBubble:
  React.FC<MessageBubbleProps> = ({
    message
  }) => {

    const isUser =
      message.role ===
        'user';


    const activeAgent =
      message.agent ??
      DEFAULT_AGENT;


    const visuals =
      getAgentVisuals(
        activeAgent
      );


    /*
     * ========================================================
     * Live processing state
     * ========================================================
     */

    if (
      message.isTyping
    ) {

      return (

        <div
          className="
            flex
            w-full
            mb-8
            justify-start
            animate-fade-in
          "
        >

          <div
            className="
              flex
              gap-3
              max-w-4xl
              w-full
            "
          >

            {/* ================================================
                Active agent avatar
            ================================================ */}

            <div
              className="
                relative
                shrink-0
                mt-1
              "
            >

              <div
                className={`
                  absolute
                  -inset-1
                  rounded-xl
                  bg-gradient-to-br
                  ${visuals.glow}
                  opacity-25
                  blur-md
                  transition-all
                  duration-500
                `}
              />


              <div
                className={`
                  relative
                  w-10
                  h-10
                  rounded-xl

                  bg-gradient-to-br
                  ${visuals.avatar}

                  flex
                  items-center
                  justify-center

                  text-white

                  shadow-lg
                  shadow-blue-500/10

                  ring-1
                  ring-white/20

                  transition-all
                  duration-500
                `}
              >

                <BotIcon
                  className="
                    w-5
                    h-5
                  "
                />

              </div>


              <span
                className="
                  absolute
                  -right-1
                  -bottom-1
                  flex
                  h-3.5
                  w-3.5
                "
              >

                <span
                  className={`
                    animate-ping
                    absolute
                    inline-flex
                    h-full
                    w-full
                    rounded-full
                    ${visuals.dot}
                    opacity-60
                  `}
                />

                <span
                  className={`
                    relative
                    inline-flex
                    rounded-full
                    h-3.5
                    w-3.5
                    ${visuals.dot}
                    border-2
                    border-white
                    dark:border-slate-900
                  `}
                />

              </span>

            </div>


            {/* ================================================
                Live routing content
            ================================================ */}

            <div
              className="
                flex
                flex-col
                items-start
                min-w-0
              "
            >

              <div
                className="
                  flex
                  items-center
                  gap-2
                  mb-1.5
                  px-1
                "
              >

                <span
                  className="
                    text-xs
                    font-semibold
                    text-slate-700
                    dark:text-slate-300
                  "
                >
                  TrialScout AI
                </span>


                <span
                  className={`
                    text-[10px]
                    uppercase
                    tracking-wider
                    font-semibold
                    px-2
                    py-0.5
                    rounded-full
                    transition-all
                    duration-300
                    ${visuals.badge}
                  `}
                >
                  {activeAgent.label}
                </span>

              </div>


              <AgentRoute
                route={
                  message.agentRoute
                }
              />


              <div
                className="
                  bg-white
                  dark:bg-slate-800

                  border
                  border-slate-200
                  dark:border-slate-700

                  rounded-2xl
                  rounded-tl-md

                  px-5
                  py-4

                  shadow-sm

                  flex
                  items-center
                  gap-4
                "
              >

                <div
                  className="
                    flex
                    gap-1.5
                  "
                >

                  <span
                    className="
                      w-2
                      h-2
                      bg-blue-500
                      rounded-full
                      animate-bounce
                    "
                    style={{
                      animationDelay:
                        '0ms'
                    }}
                  />

                  <span
                    className="
                      w-2
                      h-2
                      bg-cyan-500
                      rounded-full
                      animate-bounce
                    "
                    style={{
                      animationDelay:
                        '150ms'
                    }}
                  />

                  <span
                    className="
                      w-2
                      h-2
                      bg-teal-500
                      rounded-full
                      animate-bounce
                    "
                    style={{
                      animationDelay:
                        '300ms'
                    }}
                  />

                </div>


                <div
                  className="
                    flex
                    flex-col
                    gap-0.5
                  "
                >

                  <span
                    className="
                      text-sm
                      text-slate-600
                      dark:text-slate-300
                      font-medium
                    "
                  >
                    {activeAgent.activity}
                  </span>


                  <span
                    className="
                      text-[10px]
                      text-slate-400
                      dark:text-slate-500
                    "
                  >
                    Processing through TrialScout Agent Runtime
                  </span>

                </div>

              </div>

            </div>

          </div>

        </div>

      );

    }


    /*
     * ========================================================
     * Normal message
     * ========================================================
     */

    return (

      <div
        className={`
          flex
          w-full
          mb-8
          animate-slide-up

          ${
            isUser
              ? 'justify-end'
              : 'justify-start'
          }
        `}
      >

        <div
          className={`
            flex
            gap-3
            max-w-4xl

            ${
              isUser
                ? 'flex-row-reverse'
                : 'flex-row w-full'
            }
          `}
        >

          {/* ==================================================
              Avatar
          ================================================== */}

          {
            isUser
              ? (

                <div
                  className="
                    w-9
                    h-9
                    rounded-full

                    flex
                    items-center
                    justify-center

                    shrink-0
                    mt-6

                    bg-slate-200
                    dark:bg-slate-700

                    text-slate-600
                    dark:text-slate-200

                    border
                    border-slate-300
                    dark:border-slate-600
                  "
                >

                  <UserIcon
                    className="
                      w-4
                      h-4
                    "
                  />

                </div>

              )
              : (

                <div
                  className="
                    relative
                    shrink-0
                    mt-6
                  "
                >

                  <div
                    className={`
                      absolute
                      -inset-1
                      rounded-xl

                      bg-gradient-to-br
                      ${visuals.glow}

                      opacity-20
                      blur-md
                    `}
                  />


                  <div
                    className={`
                      relative
                      w-10
                      h-10
                      rounded-xl

                      bg-gradient-to-br
                      ${visuals.avatar}

                      flex
                      items-center
                      justify-center

                      text-white

                      shadow-lg
                      shadow-blue-500/10

                      ring-1
                      ring-white/20
                    `}
                  >

                    <BotIcon
                      className="
                        w-5
                        h-5
                      "
                    />

                  </div>


                  <span
                    className="
                      absolute
                      -right-1
                      -bottom-1

                      inline-flex
                      rounded-full

                      h-3.5
                      w-3.5

                      bg-emerald-500

                      border-2
                      border-white
                      dark:border-slate-900
                    "
                  />

                </div>

              )
          }


          {/* ==================================================
              Message content
          ================================================== */}

          <div
            className={`
              flex
              flex-col
              min-w-0

              ${
                isUser
                  ? 'items-end max-w-[80%]'
                  : 'items-start w-full'
              }
            `}
          >

            {/* ================================================
                Sender / specialist label
            ================================================ */}

            <div
              className={`
                flex
                items-center
                gap-2
                mb-1.5
                px-1

                ${
                  isUser
                    ? 'flex-row-reverse'
                    : ''
                }
              `}
            >

              <span
                className="
                  text-xs
                  font-semibold
                  text-slate-700
                  dark:text-slate-300
                "
              >

                {
                  isUser
                    ? 'You'
                    : 'TrialScout AI'
                }

              </span>


              {
                !isUser && (

                  <span
                    className={`
                      text-[10px]
                      uppercase
                      tracking-wider
                      font-semibold

                      px-2
                      py-0.5

                      rounded-full

                      ${visuals.badge}
                    `}
                  >
                    {activeAgent.label}
                  </span>

                )
              }

            </div>


            {
              !isUser && (

                <AgentRoute
                  route={
                    message.agentRoute
                  }
                />

              )
            }


            {/* ================================================
                Main bubble
            ================================================ */}

            <div
              className={`
                text-[15px]
                leading-relaxed
                shadow-sm

                ${
                  isUser

                    ? `
                      px-5
                      py-3.5

                      bg-gradient-to-br
                      from-blue-600
                      to-blue-700

                      text-white

                      rounded-2xl
                      rounded-tr-md
                    `

                    : `
                      w-full

                      px-5
                      sm:px-6
                      py-5

                      bg-white
                      dark:bg-slate-800/90

                      border
                      border-slate-200
                      dark:border-slate-700

                      text-slate-800
                      dark:text-slate-200

                      rounded-2xl
                      rounded-tl-md

                      shadow-slate-200/40
                      dark:shadow-black/10
                    `
                }
              `}
            >

              {
                isUser
                  ? (

                    <div
                      className="
                        whitespace-pre-wrap
                        break-words
                      "
                    >
                      {message.text}
                    </div>

                  )
                  : (

                    <div
                      className="
                        break-words
                        overflow-hidden
                      "
                    >

                      <ReactMarkdown

                        remarkPlugins={[
                          remarkGfm,
                          remarkMath
                        ]}

                        rehypePlugins={[
                          rehypeKatex
                        ]}

                        components={{

                          h1: ({
                            children
                          }) => (

                            <h1
                              className="
                                text-xl
                                sm:text-2xl
                                font-bold
                                text-slate-900
                                dark:text-white
                                mt-5
                                mb-3
                                first:mt-0
                              "
                            >
                              {children}
                            </h1>

                          ),


                          h2: ({
                            children
                          }) => (

                            <h2
                              className="
                                text-lg
                                sm:text-xl
                                font-bold
                                text-slate-900
                                dark:text-white
                                mt-6
                                mb-3
                                first:mt-0
                              "
                            >
                              {children}
                            </h2>

                          ),


                          h3: ({
                            children
                          }) => (

                            <h3
                              className="
                                text-base
                                sm:text-lg
                                font-semibold
                                text-slate-900
                                dark:text-white
                                mt-5
                                mb-3
                                first:mt-0
                                pl-3
                                border-l-2
                                border-blue-500
                              "
                            >
                              {children}
                            </h3>

                          ),


                          p: ({
                            children
                          }) => (

                            <p
                              className="
                                text-slate-700
                                dark:text-slate-300
                                leading-7
                                mb-4
                                last:mb-0
                              "
                            >
                              {children}
                            </p>

                          ),


                          strong: ({
                            children
                          }) => (

                            <strong
                              className="
                                font-semibold
                                text-slate-900
                                dark:text-slate-100
                              "
                            >
                              {children}
                            </strong>

                          ),


                          em: ({
                            children
                          }) => (

                            <em
                              className="
                                italic
                                text-slate-600
                                dark:text-slate-300
                              "
                            >
                              {children}
                            </em>

                          ),


                          a: ({
                            href,
                            children
                          }) => (

                            <a
                              href={
                                href
                              }

                              target="_blank"

                              rel="noopener noreferrer"

                              className="
                                text-blue-600
                                dark:text-blue-400
                                font-medium

                                hover:text-blue-700
                                dark:hover:text-blue-300

                                underline
                                decoration-blue-300/50
                                underline-offset-2

                                transition-colors
                              "
                            >
                              {children}
                            </a>

                          ),


                          ul: ({
                            children
                          }) => (

                            <ul
                              className="
                                list-disc
                                pl-6
                                mb-4
                                space-y-2
                                marker:text-blue-500
                              "
                            >
                              {children}
                            </ul>

                          ),


                          ol: ({
                            children
                          }) => (

                            <ol
                              className="
                                list-decimal
                                pl-6
                                mb-4
                                space-y-2
                                marker:text-blue-500
                                marker:font-semibold
                              "
                            >
                              {children}
                            </ol>

                          ),


                          li: ({
                            children
                          }) => (

                            <li
                              className="
                                text-slate-700
                                dark:text-slate-300
                                pl-1
                                leading-7
                              "
                            >
                              {children}
                            </li>

                          ),


                          hr: () => (

                            <div
                              className="
                                my-6
                                h-px
                                w-full

                                bg-gradient-to-r
                                from-transparent
                                via-slate-300
                                to-transparent

                                dark:via-slate-600
                              "
                            />

                          ),


                          blockquote: ({
                            children
                          }) => (

                            <blockquote
                              className="
                                my-4
                                pl-4
                                py-2

                                border-l-4
                                border-blue-400

                                bg-blue-50/60
                                dark:bg-blue-500/5

                                rounded-r-lg

                                text-slate-600
                                dark:text-slate-300
                              "
                            >
                              {children}
                            </blockquote>

                          ),


                          code: ({
                            children
                          }) => (

                            <code
                              className="
                                px-1.5
                                py-0.5
                                rounded

                                bg-slate-100
                                dark:bg-slate-900

                                text-pink-600
                                dark:text-pink-300

                                text-[0.9em]
                                font-mono
                              "
                            >
                              {children}
                            </code>

                          ),


                          table: ({
                            children
                          }) => (

                            <div
                              className="
                                w-full
                                overflow-x-auto
                                my-5

                                border
                                border-slate-200
                                dark:border-slate-700

                                rounded-xl
                              "
                            >

                              <table
                                className="
                                  w-full
                                  text-sm
                                  border-collapse
                                "
                              >
                                {children}
                              </table>

                            </div>

                          ),


                          thead: ({
                            children
                          }) => (

                            <thead
                              className="
                                bg-slate-100
                                dark:bg-slate-900/70
                              "
                            >
                              {children}
                            </thead>

                          ),


                          th: ({
                            children
                          }) => (

                            <th
                              className="
                                text-left
                                px-4
                                py-3

                                font-semibold

                                text-slate-800
                                dark:text-slate-200

                                border-b
                                border-slate-200
                                dark:border-slate-700
                              "
                            >
                              {children}
                            </th>

                          ),


                          td: ({
                            children
                          }) => (

                            <td
                              className="
                                px-4
                                py-3

                                text-slate-600
                                dark:text-slate-300

                                border-b
                                last:border-b-0

                                border-slate-100
                                dark:border-slate-700/70

                                align-top
                              "
                            >
                              {children}
                            </td>

                          )

                        }}

                      >
                        {message.text}
                      </ReactMarkdown>

                    </div>

                  )
              }

            </div>


            {/* ================================================
                Existing TrialCard support
            ================================================ */}

            {
              message.trials &&
              message.trials.length >
                0 && (

                <div
                  className="
                    mt-5
                    w-full
                    flex
                    flex-col
                    gap-3
                  "
                >

                  <div
                    className="
                      flex
                      items-center
                      gap-3
                      px-1
                    "
                  >

                    <div
                      className="
                        h-px
                        flex-1
                        bg-slate-200
                        dark:bg-slate-700
                      "
                    />


                    <span
                      className="
                        text-xs
                        font-medium
                        text-slate-500
                        dark:text-slate-400
                        uppercase
                        tracking-wider
                      "
                    >

                      {message.trials.length}

                      {
                        message.trials.length ===
                          1
                          ? ' Trial Found'
                          : ' Trials Found'
                      }

                    </span>


                    <div
                      className="
                        h-px
                        flex-1
                        bg-slate-200
                        dark:bg-slate-700
                      "
                    />

                  </div>


                  {
                    message.trials.map(
                      trial => (

                        <TrialCard

                          key={
                            trial.id
                          }

                          trial={
                            trial
                          }

                        />

                      )
                    )
                  }

                </div>

              )
            }

          </div>

        </div>

      </div>

    );

  };