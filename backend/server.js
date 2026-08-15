/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import 'dotenv/config';
import express from 'express';
import { GoogleAuth } from 'google-auth-library';
import fetch from 'node-fetch';
import rateLimit from 'express-rate-limit';
import { WebSocketServer, WebSocket } from 'ws';

const app = express();

app.use(
  express.json({
    limit: process?.env?.API_PAYLOAD_MAX_SIZE || '7mb',
  })
);

const PORT = process?.env?.API_BACKEND_PORT || 5000;
const API_BACKEND_HOST =
  process?.env?.API_BACKEND_HOST || '127.0.0.1';

const GOOGLE_CLOUD_LOCATION =
  process?.env?.GOOGLE_CLOUD_LOCATION;

const GOOGLE_CLOUD_PROJECT =
  process?.env?.GOOGLE_CLOUD_PROJECT;

if (!GOOGLE_CLOUD_PROJECT || !GOOGLE_CLOUD_LOCATION) {
  console.error(
    'Error: Environment variables GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION must be set.'
  );
  process.exit(1);
}

const PROXY_HEADER = process?.env?.PROXY_HEADER;

if (!PROXY_HEADER) {
  console.error(
    'Error: Environment variable PROXY_HEADER must be set.'
  );
  process.exit(1);
}

app.set('trust proxy', 1);

/*
 * ------------------------------------------------------------
 * Rate limiting
 * ------------------------------------------------------------
 *
 * Protects the Google Cloud proxy endpoint from excessive calls.
 */

const proxyLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: 'Too many requests',
    message:
      'You have exceeded the request limit. Please try again later.',
  },
});

app.use('/api-proxy', proxyLimiter);

/*
 * ------------------------------------------------------------
 * Supported Google Cloud API clients
 * ------------------------------------------------------------
 *
 * The original App Builder backend supported:
 *
 *   - generateContent
 *   - predict
 *   - streamGenerateContent
 *
 * TrialScout additionally needs:
 *
 *   - Reasoning Engine query
 *   - Reasoning Engine streamQuery
 *
 * These are required for communication with the deployed
 * TrialScout ADK Agent Runtime.
 */

const API_CLIENT_MAP = [
  /*
   * ----------------------------------------------------------
   * Vertex AI Gemini - generateContent
   * ----------------------------------------------------------
   */
  {
    name: 'VertexGenAi:generateContent',

    patternForProxy:
      'https://aiplatform.googleapis.com/{{version}}/publishers/google/models/{{model}}:generateContent',

    getApiEndpoint: (context, params) => {
      return (
        `https://aiplatform.clients6.google.com/` +
        `${params['version']}/projects/${context.projectId}/` +
        `locations/${context.region}/publishers/google/models/` +
        `${params['model']}:generateContent`
      );
    },

    isStreaming: false,
    transformFn: null,
  },

  /*
   * ----------------------------------------------------------
   * Vertex AI Gemini - predict
   * ----------------------------------------------------------
   */
  {
    name: 'VertexGenAi:predict',

    patternForProxy:
      'https://aiplatform.googleapis.com/{{version}}/publishers/google/models/{{model}}:predict',

    getApiEndpoint: (context, params) => {
      return (
        `https://aiplatform.clients6.google.com/` +
        `${params['version']}/projects/${context.projectId}/` +
        `locations/${context.region}/publishers/google/models/` +
        `${params['model']}:predict`
      );
    },

    isStreaming: false,
    transformFn: null,
  },

  /*
   * ----------------------------------------------------------
   * Vertex AI Gemini - streamGenerateContent
   * ----------------------------------------------------------
   */
  {
    name: 'VertexGenAi:streamGenerateContent',

    patternForProxy:
      'https://aiplatform.googleapis.com/{{version}}/publishers/google/models/{{model}}:streamGenerateContent',

    getApiEndpoint: (context, params) => {
      return (
        `https://aiplatform.clients6.google.com/` +
        `${params['version']}/projects/${context.projectId}/` +
        `locations/${context.region}/publishers/google/models/` +
        `${params['model']}:streamGenerateContent`
      );
    },

    isStreaming: true,

    transformFn: (response) => {
      let normalizedResponse = response.trim();

      while (
        normalizedResponse.startsWith(',') ||
        normalizedResponse.startsWith('[')
      ) {
        normalizedResponse =
          normalizedResponse.substring(1).trim();
      }

      while (
        normalizedResponse.endsWith(',') ||
        normalizedResponse.endsWith(']')
      ) {
        normalizedResponse = normalizedResponse
          .substring(0, normalizedResponse.length - 1)
          .trim();
      }

      if (!normalizedResponse.length) {
        return {
          result: null,
          inProgress: false,
        };
      }

      if (!normalizedResponse.endsWith('}')) {
        return {
          result: normalizedResponse,
          inProgress: true,
        };
      }

      try {
        const parsedResponse =
          JSON.parse(normalizedResponse);

        const transformedResponse =
          `data: ${JSON.stringify(parsedResponse)}\n\n`;

        return {
          result: transformedResponse,
          inProgress: false,
        };
      } catch (error) {
        throw new Error(
          `Failed to parse response: ${error}.`
        );
      }
    },
  },

  /*
   * ----------------------------------------------------------
   * TrialScout Agent Runtime - query
   * ----------------------------------------------------------
   *
   * Used for non-streaming Reasoning Engine operations.
   * This also gives us support for session-related Runtime
   * operations later.
   */

  {
    name: 'ReasoningEngine:query',

    patternForProxy:
      'https://{{region}}-aiplatform.googleapis.com/{{version}}/projects/{{project}}/locations/{{location}}/reasoningEngines/{{engine}}:query',

    getApiEndpoint: (context, params) => {
      return (
        `https://${context.region}-aiplatform.googleapis.com/` +
        `${params['version']}/projects/${context.projectId}/` +
        `locations/${context.region}/reasoningEngines/` +
        `${params['engine']}:query`
      );
    },

    isStreaming: false,
    transformFn: null,
  },

  /*
   * ----------------------------------------------------------
   * TrialScout Agent Runtime - streamQuery
   * ----------------------------------------------------------
   *
   * This is the primary endpoint that the TrialScout
   * frontend will use to send user messages to the deployed
   * ADK multi-agent system.
   */

  {
    name: 'ReasoningEngine:streamQuery',

    patternForProxy:
      'https://{{region}}-aiplatform.googleapis.com/{{version}}/projects/{{project}}/locations/{{location}}/reasoningEngines/{{engine}}:streamQuery',

    getApiEndpoint: (context, params) => {
      return (
        `https://${context.region}-aiplatform.googleapis.com/` +
        `${params['version']}/projects/${context.projectId}/` +
        `locations/${context.region}/reasoningEngines/` +
        `${params['engine']}:streamQuery?alt=sse`
      );
    },

    isStreaming: true,
    transformFn: null,
  },
].map((client) => ({
  ...client,
  patternInfo: parsePattern(
    client.patternForProxy
  ),
}));

/*
 * ------------------------------------------------------------
 * SSRF protection
 * ------------------------------------------------------------
 *
 * IMPORTANT:
 * Keep this list restrictive.
 *
 * The authenticated backend must NEVER be turned into an
 * unrestricted proxy because it carries Google OAuth
 * credentials.
 */

const ALLOWED_UPSTREAM_HOSTS = new Set([
  /*
   * Gemini API endpoint used by the original App Builder code.
   */
  'aiplatform.clients6.google.com',

  /*
   * TrialScout Agent Runtime.
   *
   * TrialScout is deployed in us-central1.
   */
  'us-central1-aiplatform.googleapis.com',
]);

/*
 * ------------------------------------------------------------
 * Google Cloud authentication
 * ------------------------------------------------------------
 *
 * Local development:
 *
 *   gcloud auth application-default login
 *
 * When deployed to Google Cloud, ADC can use the attached
 * service account instead of storing credentials in the
 * browser or source code.
 */

const auth = new GoogleAuth({
  scopes: [
    'https://www.googleapis.com/auth/cloud-platform',
  ],
});

/*
 * ------------------------------------------------------------
 * Utility functions
 * ------------------------------------------------------------
 */

function escapeRegex(str) {
  return str.replace(
    /[.*+?^${}()|[\]\\]/g,
    '\\$&'
  );
}

function parsePattern(pattern) {
  const paramRegex = /\{\{(.*?)\}\}/g;

  const params = [];
  const parts = [];

  let lastIndex = 0;
  let match;

  while (
    (match = paramRegex.exec(pattern)) !== null
  ) {
    params.push(match[1]);

    const literalPart = pattern.substring(
      lastIndex,
      match.index
    );

    parts.push(
      escapeRegex(literalPart)
    );

    parts.push(
      `(?<${match[1]}>[^/]+)`
    );

    lastIndex = paramRegex.lastIndex;
  }

  parts.push(
    escapeRegex(
      pattern.substring(lastIndex)
    )
  );

  const regexString =
    parts.join('');

  return {
    regex: new RegExp(
      `^${regexString}$`
    ),
    params,
  };
}

function extractParams(
  patternInfo,
  url
) {
  const match =
    url.match(patternInfo.regex);

  if (!match) {
    return null;
  }

  const params = {};

  patternInfo.params.forEach(
    (paramName, index) => {
      params[paramName] =
        match[index + 1];
    }
  );

  return params;
}

/*
 * ------------------------------------------------------------
 * Get Google access token
 * ------------------------------------------------------------
 */

async function getAccessToken(res) {
  try {
    const authClient =
      await auth.getClient();

    const token =
      await authClient.getAccessToken();

    return token.token;
  } catch (error) {
    console.error(
      '[Node Proxy] Authentication error:',
      error
    );

    if (!res) {
      return null;
    }

    if (
      error.code ===
        'ERR_GCLOUD_NOT_LOGGED_IN' ||
      (
        error.message &&
        error.message.includes(
          'Could not load the default credentials'
        )
      )
    ) {
      res.status(401).json({
        error:
          'Authentication Required',

        message:
          'Google Cloud Application Default Credentials were not found or are invalid. Run "gcloud auth application-default login" and try again.',
      });
    } else {
      res.status(500).json({
        error:
          `Authentication failed: ${error.message}`,
      });
    }

    return null;
  }
}

/*
 * ------------------------------------------------------------
 * Headers sent to Google Cloud APIs
 * ------------------------------------------------------------
 */

function getRequestHeaders(
  accessToken
) {
  return {
    Authorization:
      `Bearer ${accessToken}`,

    'X-Goog-User-Project':
      GOOGLE_CLOUD_PROJECT,

    'Content-Type':
      'application/json',
  };
}

/*
 * ============================================================
 * Google Cloud API Proxy
 * ============================================================
 */

app.post(
  '/api-proxy',
  async (req, res) => {
    /*
     * Verify that the request originated from the
     * App Builder frontend shim.
     */

    if (
      req.headers['x-app-proxy'] !==
      PROXY_HEADER
    ) {
      return res
        .status(403)
        .send(
          'Forbidden: Request must originate from the Vertex App shim.'
        );
    }

    const {
      originalUrl,
      method,
      headers,
      body,
    } = req.body;

    if (!originalUrl) {
      return res
        .status(400)
        .send(
          'Bad Request: originalUrl is required.'
        );
    }

    /*
     * --------------------------------------------------------
     * Find matching API handler
     * --------------------------------------------------------
     */

    let extractedParams = null;

    const apiClient =
      API_CLIENT_MAP.find(
        (client) => {
          const params =
            extractParams(
              client.patternInfo,
              originalUrl
            );

          if (params !== null) {
            extractedParams =
              params;

            return true;
          }

          return false;
        }
      );

    if (!apiClient) {
      console.error(
        `[Node Proxy] No API client handler found for URL: ${originalUrl}`
      );

      return res.status(404).json({
        error:
          `No proxy handler found for URL: ${originalUrl}`,
      });
    }

    console.log(
      `[Node Proxy] Matched API client: ${apiClient.name}`
    );

    try {
      /*
       * ------------------------------------------------------
       * Authentication
       * ------------------------------------------------------
       */

      const accessToken =
        await getAccessToken(res);

      if (!accessToken) {
        return;
      }

      /*
       * ------------------------------------------------------
       * Build Google API URL
       * ------------------------------------------------------
       */

      const context = {
        projectId:
          GOOGLE_CLOUD_PROJECT,

        region:
          GOOGLE_CLOUD_LOCATION,
      };

      const apiUrl =
        apiClient.getApiEndpoint(
          context,
          extractedParams
        );

      /*
       * ------------------------------------------------------
       * SSRF validation
       * ------------------------------------------------------
       */

      let parsedApiUrl;

      try {
        parsedApiUrl =
          new URL(apiUrl);
      } catch (error) {
        console.error(
          `[Node Proxy] Invalid API URL: ${apiUrl}`
        );

        return res
          .status(400)
          .json({
            error:
              'Invalid API URL.',
          });
      }

      const upstreamHostname =
        parsedApiUrl.hostname.toLowerCase();

      if (
        !ALLOWED_UPSTREAM_HOSTS.has(
          upstreamHostname
        )
      ) {
        console.error(
          `[Node Proxy] Upstream host not allowed: ${upstreamHostname}`
        );

        return res
          .status(400)
          .json({
            error:
              'Upstream host not allowed.',
          });
      }

      console.log(
        `[Node Proxy] Forwarding to Vertex API: ${apiUrl}`
      );

      /*
       * ------------------------------------------------------
       * Upstream request
       * ------------------------------------------------------
       */

      const apiHeaders =
        getRequestHeaders(
          accessToken
        );

      const apiFetchOptions = {
        method:
          method || 'POST',

        headers: {
          ...apiHeaders,
          ...headers,
        },

        body:
          body
            ? body
            : undefined,
      };

      const apiResponse =
        await fetch(
          apiUrl,
          apiFetchOptions
        );

      /*
       * ------------------------------------------------------
       * Streaming responses
       * ------------------------------------------------------
       */

      if (apiClient.isStreaming) {
        console.log(
          `[Node Proxy] Sending STREAMING response for ${apiClient.name}`
        );

        res.writeHead(
          apiResponse.status,
          {
            'Content-Type':
              'text/event-stream',

            'Transfer-Encoding':
              'chunked',

            Connection:
              'keep-alive',

            'Cache-Control':
              'no-cache',
          }
        );

        res.flushHeaders();

        if (!apiResponse.body) {
          console.error(
            '[Node Proxy] Streaming response has no body.'
          );

          return res.end(
            JSON.stringify({
              error:
                'Streaming response body is null',
            })
          );
        }

        const decoder =
          new TextDecoder();

        let deltaChunk = '';

        apiResponse.body.on(
          'data',
          (encodedChunk) => {
            if (
              res.writableEnded
            ) {
              return;
            }

            try {
              /*
               * Reasoning Engine streamQuery does not need
               * Gemini's stream response transformation.
               */

              if (
                !apiClient.transformFn
              ) {
                res.write(
                  encodedChunk
                );

                return;
              }

              /*
               * Gemini streaming transformation.
               */

              const decodedChunk =
                decoder.decode(
                  encodedChunk,
                  {
                    stream: true,
                  }
                );

              deltaChunk +=
                decodedChunk;

              const {
                result,
                inProgress,
              } =
                apiClient.transformFn(
                  deltaChunk
                );

              if (
                result &&
                !inProgress
              ) {
                deltaChunk = '';

                res.write(
                  new TextEncoder().encode(
                    result
                  )
                );
              }
            } catch (error) {
              console.error(
                `[Node Proxy] Error processing streaming response for ${apiClient.name}`
              );

              console.error(
                error
              );
            }
          }
        );

        apiResponse.body.on(
          'end',
          () => {
            deltaChunk = '';

            console.log(
              `[Node Proxy] Vertex stream finished for ${apiClient.name}`
            );

            res.end();
          }
        );

        apiResponse.body.on(
          'error',
          (streamError) => {
            console.error(
              '[Node Proxy] Error from Vertex stream:',
              streamError
            );

            if (
              !res.writableEnded
            ) {
              res.end(
                JSON.stringify({
                  proxyError:
                    'Stream error from Vertex AI',

                  details:
                    streamError.message,
                })
              );
            }
          }
        );

        res.on(
          'error',
          (resError) => {
            console.error(
              '[Node Proxy] Error writing to client response:',
              resError
            );

            if (
              apiResponse.body &&
              typeof apiResponse.body.destroy ===
                'function'
            ) {
              apiResponse.body.destroy(
                resError
              );
            }
          }
        );

        return;
      }

      /*
       * ------------------------------------------------------
       * Non-streaming response
       * ------------------------------------------------------
       */

      console.log(
        `[Node Proxy] Sending JSON response for ${apiClient.name}`
      );

      const data =
        await apiResponse.json();

      return res
        .status(apiResponse.status)
        .json(data);
    } catch (error) {
      console.error(
        `[Node Proxy] Error proxying request for ${apiClient.name}`
      );

      console.error(error);

      return res
        .status(500)
        .json({
          error:
            error?.message ||
            String(error),
        });
    }
  }
);

/*
 * ============================================================
 * Start HTTP server
 * ============================================================
 */

const server = app.listen(
  PORT,
  API_BACKEND_HOST,
  () => {
    console.log(
      `Vertex AI Backend listening at http://localhost:${PORT}`
    );

    console.log(
      `Google Cloud project: ${GOOGLE_CLOUD_PROJECT}`
    );

    console.log(
      `Google Cloud location: ${GOOGLE_CLOUD_LOCATION}`
    );

    console.log(
      'TrialScout Agent Runtime proxy support enabled.'
    );
  }
);

/*
 * ============================================================
 * WebSocket proxy
 * ============================================================
 *
 * This functionality comes from Google's generated App Builder
 * backend and is retained for compatibility with Vertex AI
 * Live API functionality.
 */

const wss =
  new WebSocketServer({
    noServer: true,
  });

server.on(
  'upgrade',
  async (
    request,
    socket,
    head
  ) => {
    const url =
      new URL(
        request.url,
        `http://${request.headers.host}`
      );

    if (
      url.pathname !==
      '/ws-proxy'
    ) {
      socket.destroy();
      return;
    }

    let targetUrl =
      url.searchParams.get(
        'target'
      );

    if (!targetUrl) {
      console.log(
        '[Node Proxy] Missing target URL'
      );

      socket.destroy();
      return;
    }

    /*
     * Only Google's supported Live API WebSocket endpoint
     * is allowed.
     */

    if (
      targetUrl ===
      'wss://aiplatform.googleapis.com//ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'
    ) {
      const location =
        GOOGLE_CLOUD_LOCATION ===
        'global'
          ? 'us-central1'
          : GOOGLE_CLOUD_LOCATION;

      targetUrl =
        `wss://${location}-aiplatform.googleapis.com//ws/` +
        `google.cloud.aiplatform.v1beta1.LlmBidiService/` +
        `BidiGenerateContent`;
    } else {
      console.log(
        '[Node Proxy] Invalid target URL'
      );

      socket.destroy();
      return;
    }

    /*
     * Authenticate upstream WebSocket.
     */

    let accessToken;

    try {
      accessToken =
        await getAccessToken();

      if (!accessToken) {
        throw new Error(
          'No Google access token'
        );
      }
    } catch (error) {
      console.log(
        '[Node Proxy] Authentication failed'
      );

      socket.destroy();
      return;
    }

    console.log(
      `[Node Proxy] Initiating upstream connection to: ${targetUrl}`
    );

    let upstreamWs;

    try {
      upstreamWs =
        new WebSocket(
          targetUrl,
          {
            headers:
              getRequestHeaders(
                accessToken
              ),
          }
        );
    } catch (error) {
      console.error(
        '[Node Proxy] Invalid upstream URL'
      );

      socket.destroy();
      return;
    }

    /*
     * Handle failure before the upstream WebSocket
     * has successfully opened.
     */

    const initialErrorHandler =
      (error) => {
        console.error(
          '[Node Proxy] Upstream connection failed:',
          error
        );

        upstreamWs.removeEventListener(
          'open',
          onUpstreamOpen
        );

        if (socket.writable) {
          socket.write(
            'HTTP/1.1 502 Bad Gateway\r\n\r\n'
          );

          socket.destroy();
        }
      };

    upstreamWs.once(
      'error',
      initialErrorHandler
    );

    /*
     * --------------------------------------------------------
     * Upstream WebSocket connected
     * --------------------------------------------------------
     */

    const onUpstreamOpen =
      () => {
        upstreamWs.removeListener(
          'error',
          initialErrorHandler
        );

        wss.handleUpgrade(
          request,
          socket,
          head,
          (ws) => {
            /*
             * Vertex AI -> Browser
             */

            upstreamWs.on(
              'message',
              (
                data,
                isBinary
              ) => {
                const logMsg =
                  isBinary
                    ? '<Binary Data>'
                    : data.toString();

                console.log(
                  `[Upstream -> Client] [${new Date().toISOString()}]: ${logMsg}`
                );

                if (
                  ws.readyState ===
                  WebSocket.OPEN
                ) {
                  if (
                    data ===
                      undefined ||
                    data === null
                  ) {
                    console.warn(
                      '[Node Proxy] Attempted to send undefined/null data to client'
                    );

                    return;
                  }

                  ws.send(
                    data,
                    {
                      binary:
                        isBinary,
                    }
                  );
                }
              }
            );

            /*
             * Browser -> Vertex AI
             */

            ws.on(
              'message',
              (
                data,
                isBinary
              ) => {
                let dataJson = {};

                try {
                  dataJson =
                    JSON.parse(
                      data.toString()
                    );
                } catch (error) {
                  console.error(
                    '[Node Proxy] Failed to parse message from client:',
                    error
                  );

                  ws.close(
                    1011,
                    'Failed to parse message'
                  );

                  return;
                }

                if (
                  dataJson[
                    'setup'
                  ]
                ) {
                  dataJson[
                    'setup'
                  ][
                    'model'
                  ] =
                    `projects/${GOOGLE_CLOUD_PROJECT}/` +
                    `locations/${GOOGLE_CLOUD_LOCATION}/` +
                    `${dataJson['setup']['model']}`;
                }

                if (
                  upstreamWs.readyState ===
                  WebSocket.OPEN
                ) {
                  upstreamWs.send(
                    JSON.stringify(
                      dataJson
                    ),
                    {
                      binary:
                        false,
                    }
                  );
                }
              }
            );

            /*
             * Upstream errors.
             */

            upstreamWs.on(
              'error',
              (error) => {
                console.error(
                  '[Node Proxy] Upstream error:',
                  error
                );

                ws.close(
                  1011,
                  error.message
                );
              }
            );

            /*
             * Upstream closed.
             */

            upstreamWs.on(
              'close',
              (
                code,
                reason
              ) => {
                console.log(
                  `[Node Proxy] Upstream closed: ${code} ${reason}`
                );

                if (
                  ws.readyState ===
                  WebSocket.OPEN
                ) {
                  ws.close(
                    code,
                    reason
                  );
                }
              }
            );

            /*
             * Browser errors.
             */

            ws.on(
              'error',
              (error) => {
                console.error(
                  '[Node Proxy] Client error:',
                  error
                );

                if (
                  upstreamWs.readyState ===
                  WebSocket.OPEN
                ) {
                  upstreamWs.close(
                    1011,
                    error.message
                  );
                }
              }
            );

            /*
             * Browser closed.
             */

            ws.on(
              'close',
              (
                code,
                reason
              ) => {
                console.log(
                  `[Node Proxy] Client closed: ${code} ${reason}`
                );

                if (
                  upstreamWs.readyState ===
                  WebSocket.OPEN
                ) {
                  upstreamWs.close(
                    1000,
                    reason
                  );
                }
              }
            );

            wss.emit(
              'connection',
              ws,
              request
            );
          }
        );
      };

    upstreamWs.once(
      'open',
      onUpstreamOpen
    );
  }
);