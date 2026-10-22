# One image serves all three MCP servers. MCP_SERVER picks which one (hris, ticketing, compensation).
# Build context is the repository root so the image can include data/seed.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /bin/

WORKDIR /srv
COPY mcp_servers/requirements.txt ./mcp_servers/requirements.txt
RUN uv pip install --system --no-cache -r mcp_servers/requirements.txt

COPY mcp_servers ./mcp_servers
COPY data/seed ./data/seed

ENV PYTHONUNBUFFERED=1 SEED_DIR=/srv/data/seed MCP_SERVER=hris
EXPOSE 8080
USER nobody
CMD ["sh", "-c", "exec python -m mcp_servers.${MCP_SERVER}.server"]
