FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.11.7

WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock* ./

COPY ./trialscout_agent ./trialscout_agent
COPY ./data ./data

RUN uv sync --frozen

ARG AGENT_VERSION=0.1.0
ENV AGENT_VERSION=${AGENT_VERSION}

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "trialscout_agent.fast_api_app:app", "--host", "0.0.0.0", "--port", "8080"]
