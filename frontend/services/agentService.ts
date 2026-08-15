import {
  AgentDisplayInfo,
  AgentRoutingUpdate,
  ChatMessage
} from '../types.ts';


/*
 * ============================================================
 * TrialScout Agent Runtime configuration
 * ============================================================
 */

const GOOGLE_CLOUD_PROJECT =
  'trialscout-ai';

const GOOGLE_CLOUD_LOCATION =
  'us-central1';

const REASONING_ENGINE_ID =
  '4981378661325209600';


const REASONING_ENGINE_BASE_URL =
  `https://${GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/` +
  `v1/projects/${GOOGLE_CLOUD_PROJECT}/` +
  `locations/${GOOGLE_CLOUD_LOCATION}/` +
  `reasoningEngines/${REASONING_ENGINE_ID}`;


const QUERY_URL =
  `${REASONING_ENGINE_BASE_URL}:query`;

const STREAM_QUERY_URL =
  `${REASONING_ENGINE_BASE_URL}:streamQuery?alt=sse`;


/*
 * ============================================================
 * Local browser session storage
 * ============================================================
 */

const USER_ID_STORAGE_KEY =
  'trialscout_user_id';

const SESSION_ID_STORAGE_KEY =
  'trialscout_session_id';


/*
 * ============================================================
 * Public Orchestrator definition
 * ============================================================
 *
 * App.tsx uses this before Agent Runtime tells us which
 * specialist agent has been selected.
 */

export const ORCHESTRATOR_AGENT:
  AgentDisplayInfo = {

    key:
      'orchestrator',

    label:
      'Orchestrator',

    activity:
      'Understanding your request and selecting the right specialist...',

    runtimeName:
      'TrialScout_AI'
  };


/*
 * ============================================================
 * Known specialist agent mappings
 * ============================================================
 *
 * IMPORTANT:
 *
 * These mappings are UI labels only.
 *
 * We still detect the ACTUAL agent from Agent Runtime events.
 * We are NOT deciding the route based on the user's button or
 * query text.
 */

const getAgentDisplayInfo =
  (
    runtimeName:
      string | undefined
  ): AgentDisplayInfo | null => {

    if (!runtimeName) {
      return null;
    }


    const normalized =
      runtimeName
        .trim()
        .toLowerCase();


    /*
     * Root orchestration agent
     */

    if (
      normalized ===
        'trialscout_ai' ||
      normalized ===
        'trialscout-ai'
    ) {

      return {
        ...ORCHESTRATOR_AGENT,
        runtimeName
      };

    }


    /*
     * Clinical trial discovery
     */

    if (
      normalized.includes(
        'trial_discovery_agent'
      )
    ) {

      return {
        key:
          'discovery',

        label:
          'Discovery Agent',

        activity:
          'Searching live clinical trial data and relevant study locations...',

        runtimeName
      };

    }


    /*
     * Detailed single-trial analysis
     */

    if (
      normalized.includes(
        'trial_analysis_agent'
      )
    ) {

      return {
        key:
          'analysis',

        label:
          'Trial Analysis Agent',

        activity:
          'Retrieving and analyzing detailed study information...',

        runtimeName
      };

    }


    /*
     * FHIR / patient screening
     */

    if (
      normalized.includes(
        'fhir_screening_agent'
      )
    ) {

      return {
        key:
          'fhir_screening',

        label:
          'FHIR Screening Agent',

        activity:
          'Reviewing patient information and preliminary screening evidence...',

        runtimeName
      };

    }


    /*
     * Trial comparison / matching / ranking
     *
     * Supports both one-underscore and two-underscore forms.
     */

    if (
      normalized.includes(
        'trial_matching__ranking_agent'
      ) ||
      normalized.includes(
        'trial_matching_ranking_agent'
      )
    ) {

      return {
        key:
          'matching_ranking',

        label:
          'Matching & Ranking Agent',

        activity:
          'Comparing studies and evaluating preliminary trial alignment...',

        runtimeName
      };

    }


    /*
     * Clinical research knowledge
     */

    if (
      normalized.includes(
        'clinical_research_knowledge_agent'
      )
    ) {

      return {
        key:
          'research_knowledge',

        label:
          'Research Knowledge Agent',

        activity:
          'Researching clinical study concepts and supporting information...',

        runtimeName
      };

    }


    /*
     * URL context specialist
     */

    if (
      normalized.includes(
        'url_context_agent'
      )
    ) {

      return {
        key:
          'url_context',

        label:
          'URL Context Agent',

        activity:
          'Reviewing the referenced clinical research content...',

        runtimeName
      };

    }


    /*
     * Ignore unknown function/tool names.
     *
     * This prevents MCP tools such as search functions from
     * being incorrectly displayed as specialist agents.
     */

    return null;
  };


/*
 * ============================================================
 * Utility helpers
 * ============================================================
 */

const generateId =
  (): string =>

    Math.random()
      .toString(36)
      .substring(2, 9);


/*
 * Anonymous browser-local user identity.
 *
 * Never put patient information inside this ID.
 */

const getOrCreateUserId =
  (): string => {

    const existingUserId =
      localStorage.getItem(
        USER_ID_STORAGE_KEY
      );


    if (existingUserId) {
      return existingUserId;
    }


    let newUserId:
      string;


    if (
      typeof crypto !==
        'undefined' &&
      typeof crypto.randomUUID ===
        'function'
    ) {

      newUserId =
        `trialscout-web-${crypto.randomUUID()}`;

    } else {

      newUserId =
        `trialscout-web-${Date.now()}-${generateId()}`;

    }


    localStorage.setItem(
      USER_ID_STORAGE_KEY,
      newUserId
    );


    return newUserId;
  };


/*
 * ============================================================
 * Agent Runtime session creation
 * ============================================================
 */

const createAgentSession =
  async (
    userId:
      string
  ): Promise<string> => {

    console.log(
      '[TrialScout] Creating Agent Runtime session...'
    );


    const response =
      await fetch(
        QUERY_URL,
        {
          method:
            'POST',

          headers: {
            'Content-Type':
              'application/json'
          },

          body:
            JSON.stringify({
              class_method:
                'async_create_session',

              input: {
                user_id:
                  userId
              }
            })
        }
      );


    if (!response.ok) {

      const errorText =
        await response.text();


      throw new Error(
        `Failed to create TrialScout session. ` +
        `HTTP ${response.status}: ${errorText}`
      );

    }


    const data =
      await response.json();


    const sessionId =
      data?.output?.id ||
      data?.output?.session_id ||
      data?.id ||
      data?.session_id ||
      data?.session?.id;


    if (!sessionId) {

      console.error(
        '[TrialScout] Unexpected session response:',
        data
      );


      throw new Error(
        'Agent Runtime returned a session response, but no session ID could be found.'
      );

    }


    localStorage.setItem(
      SESSION_ID_STORAGE_KEY,
      sessionId
    );


    console.log(
      '[TrialScout] Agent Runtime session created.'
    );


    return sessionId;
  };


const getOrCreateSessionId =
  async (
    userId:
      string
  ): Promise<string> => {

    const existingSessionId =
      localStorage.getItem(
        SESSION_ID_STORAGE_KEY
      );


    if (existingSessionId) {
      return existingSessionId;
    }


    return await createAgentSession(
      userId
    );
  };


/*
 * ============================================================
 * Stream event helpers
 * ============================================================
 */

const normalizeEvent =
  (
    rawEvent:
      any
  ) =>

    rawEvent?.output ??
    rawEvent;


/*
 * Detect an actual TrialScout specialist from an Agent Runtime
 * event.
 *
 * We look at:
 *
 * 1. function_call.name
 * 2. function_response.name
 * 3. event author
 *
 * Function-call names are preferred because that is exactly
 * how the root orchestrator delegates to AgentTool agents.
 */

const detectAgentFromEvent =
  (
    rawEvent:
      any
  ): AgentDisplayInfo | null => {

    const event =
      normalizeEvent(
        rawEvent
      );


    const parts =
      event?.content?.parts;


    if (
      Array.isArray(parts)
    ) {

      /*
       * First preference:
       * actual function calls.
       */

      for (
        const part of parts
      ) {

        const functionCallName =
          part?.function_call?.name;


        const detected =
          getAgentDisplayInfo(
            functionCallName
          );


        if (detected) {
          return detected;
        }

      }


      /*
       * Second preference:
       * function responses.
       */

      for (
        const part of parts
      ) {

        const functionResponseName =
          part?.function_response?.name;


        const detected =
          getAgentDisplayInfo(
            functionResponseName
          );


        if (detected) {
          return detected;
        }

      }

    }


    /*
     * Child agent events may identify themselves through
     * "author".
     */

    const authorAgent =
      getAgentDisplayInfo(
        event?.author
      );


    if (authorAgent) {
      return authorAgent;
    }


    return null;
  };


/*
 * Extract root-model text from an event.
 *
 * As before, the latest model-authored text is treated as the
 * final TrialScout answer.
 */

const extractTextFromEvent =
  (
    rawEvent:
      any
  ): string => {

    const event =
      normalizeEvent(
        rawEvent
      );


    const content =
      event?.content;


    if (!content) {
      return '';
    }


    if (
      content.role &&
      content.role !==
        'model'
    ) {
      return '';
    }


    if (
      !Array.isArray(
        content.parts
      )
    ) {
      return '';
    }


    let text =
      '';


    for (
      const part of
        content.parts
    ) {

      if (
        typeof part?.text ===
          'string' &&
        part.text.trim()
      ) {

        text =
          part.text.trim();

      }

    }


    return text;
  };


/*
 * ============================================================
 * Send message to REAL TrialScout Agent Runtime
 * ============================================================
 *
 * onRoutingUpdate receives LIVE specialist-agent changes while
 * the Agent Runtime response is still streaming.
 */

export const mockSendMessage =
  async (
    text:
      string,

    onRoutingUpdate?:
      (
        update:
          AgentRoutingUpdate
      ) => void

  ): Promise<ChatMessage> => {

    const cleanedText =
      text.trim();


    if (!cleanedText) {

      throw new Error(
        'Message cannot be empty.'
      );

    }


    const userId =
      getOrCreateUserId();


    const sessionId =
      await getOrCreateSessionId(
        userId
      );


    /*
     * Every request begins with the root orchestrator.
     */

    let activeAgent:
      AgentDisplayInfo =
        ORCHESTRATOR_AGENT;


    const route:
      AgentDisplayInfo[] = [
        ORCHESTRATOR_AGENT
      ];


    const publishRoutingUpdate =
      () => {

        onRoutingUpdate?.({
          activeAgent:
            { ...activeAgent },

          route:
            route.map(
              agent => ({
                ...agent
              })
            )
        });

      };


    /*
     * Immediately show Orchestrator in the UI.
     */

    publishRoutingUpdate();


    console.log(
      '[TrialScout] Sending message to deployed Agent Runtime...'
    );


    const response =
      await fetch(
        STREAM_QUERY_URL,
        {
          method:
            'POST',

          headers: {
            'Content-Type':
              'application/json'
          },

          body:
            JSON.stringify({
              class_method:
                'async_stream_query',

              input: {
                user_id:
                  userId,

                session_id:
                  sessionId,

                message:
                  cleanedText
              }
            })
        }
      );


    if (!response.ok) {

      const errorText =
        await response.text();


      throw new Error(
        `TrialScout Agent Runtime request failed. ` +
        `HTTP ${response.status}: ${errorText}`
      );

    }


    /*
     * ========================================================
     * Process Runtime events as they arrive
     * ========================================================
     */

    const parsedEvents:
      any[] = [];


    let finalText =
      '';


    const processEvent =
      (
        event:
          any
      ) => {

        parsedEvents.push(
          event
        );


        /*
         * ----------------------------------------------------
         * Detect real specialist routing
         * ----------------------------------------------------
         */

        const detectedAgent =
          detectAgentFromEvent(
            event
          );


        if (
          detectedAgent &&
          detectedAgent.key !==
            'orchestrator'
        ) {

          const routeAlreadyContainsAgent =
            route.some(
              agent =>
                agent.key ===
                detectedAgent.key
            );


          if (
            !routeAlreadyContainsAgent
          ) {

            route.push(
              detectedAgent
            );

          }


          /*
           * Only trigger a UI change if the active specialist
           * actually changed.
           */

          if (
            activeAgent.key !==
            detectedAgent.key
          ) {

            activeAgent =
              detectedAgent;


            console.log(
              `[TrialScout] Routed to ${detectedAgent.label}`
            );


            publishRoutingUpdate();

          }

        }


        /*
         * ----------------------------------------------------
         * Capture final assistant text
         * ----------------------------------------------------
         */

        const eventText =
          extractTextFromEvent(
            event
          );


        if (eventText) {

          finalText =
            eventText;

        }

      };


    /*
     * Process one SSE / newline-delimited response line.
     */

    const processLine =
      (
        rawLine:
          string
      ) => {

        let line =
          rawLine.trim();


        if (!line) {
          return;
        }


        /*
         * Ignore SSE comments / metadata.
         */

        if (
          line.startsWith(':') ||
          line.startsWith(
            'event:'
          ) ||
          line.startsWith(
            'id:'
          ) ||
          line.startsWith(
            'retry:'
          )
        ) {
          return;
        }


        /*
         * Remove SSE data prefix.
         */

        if (
          line.startsWith(
            'data:'
          )
        ) {

          line =
            line
              .substring(5)
              .trim();

        }


        if (
          !line ||
          line ===
            '[DONE]'
        ) {
          return;
        }


        try {

          const parsed =
            JSON.parse(
              line
            );


          processEvent(
            parsed
          );

        } catch {

          /*
           * Some SSE control lines are not JSON.
           * They can safely be ignored.
           */

          console.debug(
            '[TrialScout] Ignoring non-JSON stream line.'
          );

        }

      };


    /*
     * ========================================================
     * Read stream progressively
     * ========================================================
     */

    if (
      response.body &&
      typeof response.body.getReader ===
        'function'
    ) {

      const reader =
        response.body.getReader();


      const decoder =
        new TextDecoder();


      let buffer =
        '';


      while (true) {

        const {
          value,
          done
        } =
          await reader.read();


        if (done) {
          break;
        }


        buffer +=
          decoder.decode(
            value,
            {
              stream:
                true
            }
          );


        const lines =
          buffer.split(
            /\r?\n/
          );


        /*
         * Last item may be only half of a JSON event.
         */

        buffer =
          lines.pop() ??
          '';


        for (
          const line of lines
        ) {

          processLine(
            line
          );

        }

      }


      /*
       * Flush any final decoder bytes.
       */

      buffer +=
        decoder.decode();


      if (
        buffer.trim()
      ) {

        processLine(
          buffer
        );

      }

    } else {

      /*
       * Fallback for browsers/environments without readable
       * streaming response bodies.
       */

      const rawResponse =
        await response.text();


      const lines =
        rawResponse.split(
          /\r?\n/
        );


      for (
        const line of lines
      ) {

        processLine(
          line
        );

      }

    }


    /*
     * ========================================================
     * Validate final response
     * ========================================================
     */

    if (
      parsedEvents.length ===
        0
    ) {

      throw new Error(
        'Agent Runtime returned no readable events.'
      );

    }


    if (!finalText) {

      console.error(
        '[TrialScout] Agent events:',
        parsedEvents
      );


      throw new Error(
        'TrialScout completed the request, but no final assistant text was returned.'
      );

    }


    console.log(
      '[TrialScout] Response received successfully.'
    );


    /*
     * Final ChatMessage remembers both:
     *
     * - the last specialist used
     * - the real routing path
     */

    return {

      id:
        generateId(),

      role:
        'assistant',

      text:
        finalText,

      agent:
        activeAgent,

      agentRoute:
        route.map(
          agent => ({
            ...agent
          })
        )

    };
  };


/*
 * ============================================================
 * Reset conversation
 * ============================================================
 */

export const resetAgentSession =
  (): void => {

    localStorage.removeItem(
      SESSION_ID_STORAGE_KEY
    );


    console.log(
      '[TrialScout] Conversation session reset.'
    );
  };