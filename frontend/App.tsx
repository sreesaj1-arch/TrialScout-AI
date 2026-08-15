import React, {
  useState,
  useRef,
  useEffect
} from 'react';

import {
  Header,
  type AgentStatus
} from './components/Header.tsx';

import {
  Sidebar
} from './components/Sidebar.tsx';

import {
  InputArea
} from './components/InputArea.tsx';

import {
  MessageBubble
} from './components/MessageBubble.tsx';

import {
  HeroWelcome
} from './components/HeroWelcome.tsx';

import {
  Disclaimer
} from './components/Disclaimer.tsx';

import {
  ChatMessage
} from './types.ts';

import {
  mockSendMessage,
  ORCHESTRATOR_AGENT,
  resetAgentSession
} from './services/agentService.ts';


export default function App() {

  const [
    messages,
    setMessages
  ] =
    useState<ChatMessage[]>([]);


  const [
    isLoading,
    setIsLoading
  ] =
    useState(false);


  const [
    agentStatus,
    setAgentStatus
  ] =
    useState<AgentStatus>(
      'ready'
    );


  const [
    isSidebarOpen,
    setIsSidebarOpen
  ] =
    useState(false);


  const [
    isDarkMode,
    setIsDarkMode
  ] =
    useState(true);


  const messagesEndRef =
    useRef<HTMLDivElement>(
      null
    );


  /*
   * ==========================================================
   * Theme
   * ==========================================================
   */

  useEffect(
    () => {

      document
        .documentElement
        .classList
        .add('dark');

    },
    []
  );


  const toggleTheme =
    () => {

      setIsDarkMode(
        previous =>
          !previous
      );


      document
        .documentElement
        .classList
        .toggle('dark');

    };


  /*
   * ==========================================================
   * Chat scrolling
   * ==========================================================
   */

  const scrollToBottom =
    () => {

      messagesEndRef
        .current
        ?.scrollIntoView({
          behavior:
            'smooth'
        });

    };


  useEffect(
    () => {

      scrollToBottom();

    },
    [messages]
  );


  /*
   * ==========================================================
   * Send message
   * ==========================================================
   */

  const handleSendMessage =
    async (
      text:
        string
    ) => {

      const cleanedText =
        text.trim();


      if (
        !cleanedText ||
        isLoading
      ) {
        return;
      }


      /*
       * ------------------------------------------------------
       * User message
       * ------------------------------------------------------
       */

      const userMsg:
        ChatMessage = {

        id:
          `user-${Date.now()}`,

        role:
          'user',

        text:
          cleanedText
      };


      /*
       * ------------------------------------------------------
       * Live agent-processing bubble
       * ------------------------------------------------------
       *
       * Every request begins at the TrialScout Orchestrator.
       *
       * The Runtime callback below updates this same temporary
       * message when a real specialist is detected.
       */

      const typingMsg:
        ChatMessage = {

        id:
          'typing',

        role:
          'assistant',

        text:
          '',

        isTyping:
          true,

        agent:
          ORCHESTRATOR_AGENT,

        agentRoute: [
          ORCHESTRATOR_AGENT
        ]
      };


      setMessages(
        previous => [
          ...previous,
          userMsg,
          typingMsg
        ]
      );


      setIsLoading(
        true
      );


      setAgentStatus(
        'working'
      );


      try {

        /*
         * ----------------------------------------------------
         * REAL Agent Runtime request
         * ----------------------------------------------------
         *
         * onRoutingUpdate fires whenever Agent Runtime exposes
         * an actual specialist-agent transition.
         */

        const response =
          await mockSendMessage(

            cleanedText,

            routingUpdate => {

              setMessages(
                previous =>

                  previous.map(
                    message => {

                      if (
                        message.id !==
                          'typing'
                      ) {
                        return message;
                      }


                      return {
                        ...message,

                        agent:
                          routingUpdate
                            .activeAgent,

                        agentRoute:
                          routingUpdate
                            .route
                      };

                    }
                  )
              );

            }

          );


        /*
         * Replace working bubble with final response.
         */

        setMessages(
          previous => {

            const withoutTyping =
              previous.filter(
                message =>
                  message.id !==
                  'typing'
              );


            return [
              ...withoutTyping,
              response
            ];

          }
        );


        setAgentStatus(
          'connected'
        );

      } catch (error) {

        console.error(
          'Failed to get TrialScout response:',
          error
        );


        setAgentStatus(
          'error'
        );


        setMessages(
          previous => {

            const withoutTyping =
              previous.filter(
                message =>
                  message.id !==
                  'typing'
              );


            return [
              ...withoutTyping,

              {
                id:
                  `error-${Date.now()}`,

                role:
                  'assistant',

                text:
                  'Sorry, I encountered an error connecting to the TrialScout Agent Runtime. Please try again.'
              }
            ];

          }
        );

      } finally {

        setIsLoading(
          false
        );

      }
    };


  /*
   * ==========================================================
   * New Chat
   * ==========================================================
   */

  const handleNewChat =
    () => {

      resetAgentSession();


      setMessages(
        []
      );


      setAgentStatus(
        'ready'
      );


      setIsLoading(
        false
      );

    };


  /*
   * ==========================================================
   * UI
   * ==========================================================
   */

  return (

    <div
      className="
        flex
        h-screen
        overflow-hidden
        bg-slate-50
        dark:bg-slate-900
        transition-colors
        duration-300
      "
    >

      <Sidebar

        isOpen={
          isSidebarOpen
        }

        onClose={
          () =>
            setIsSidebarOpen(
              false
            )
        }

        onNewChat={
          handleNewChat
        }

        onPromptClick={
          handleSendMessage
        }

      />


      <div
        className="
          flex-1
          flex
          flex-col
          min-w-0
        "
      >

        <Header

          isDarkMode={
            isDarkMode
          }

          toggleTheme={
            toggleTheme
          }

          toggleSidebar={
            () =>
              setIsSidebarOpen(
                previous =>
                  !previous
              )
          }

          agentStatus={
            agentStatus
          }

        />


        <main
          className="
            flex-1
            overflow-y-auto
            p-4
            sm:p-6
            scroll-smooth
          "
        >

          {
            messages.length ===
              0
              ? (

                <HeroWelcome

                  onPromptClick={
                    handleSendMessage
                  }

                />

              )
              : (

                <div
                  className="
                    max-w-4xl
                    mx-auto
                    flex
                    flex-col
                    pb-4
                  "
                >

                  {
                    messages.map(
                      message => (

                        <MessageBubble

                          key={
                            message.id
                          }

                          message={
                            message
                          }

                        />

                      )
                    )
                  }


                  <div
                    ref={
                      messagesEndRef
                    }
                  />

                </div>

              )
          }

        </main>


        <div
          className="
            bg-gradient-to-t
            from-slate-50
            via-slate-50
            to-transparent
            dark:from-slate-900
            dark:via-slate-900
            pt-4
            shrink-0
          "
        >

          <InputArea

            onSendMessage={
              handleSendMessage
            }

            disabled={
              isLoading
            }

          />


          <Disclaimer />

        </div>

      </div>

    </div>

  );
}