# Sample IBM MQ MCP server

MCP (Model Context Protocol) is an open standard that allows LLMs and AI agents to discover and interact with external services such as databases, REST APIs, files, and other resources.
You can read up on the details of MCP [here](https://modelcontextprotocol.io/introduction).

This repo contains a simple MCP server, written in Python, that exposes a subset of the [MQ Administrative REST API](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=administering-administration-using-rest-api) as two MCP tools:

- dsqmq: lists any queue managers that are local to the mqweb server, and whether they are running or not
- runmqsc: runs any MQSC command against a specific queue manager. This makes use of the [plain text MQSC API](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=adminactionqmgrqmgrnamemqsc-post-plain-text-mqsc-command) 

You can use this MCP server with any LLM which has an MCP client in it, for example [IBM Bob](https://www.ibm.com/products/bob), to allow that LLM to interact with, and potentially configure, your queue managers. 

## Getting the MQ MCP server running

This example was created based on these [instructions](https://modelcontextprotocol.io/quickstart/server). To get the MQ MCP server running, follow these steps:

- The MQ MCP server uses the MQ Administrative REST API. Ensure that you have the mqweb server running as part of a full MQ for distributed installation with one or more queue managers. This doesn't have to be on your local machine
- Ensure that you have installed Python 3.10 or higher
- Install uv and set up your Python project
    - (MacOS/Linux): **curl -LsSf https://astral.sh/uv/install.sh | sh**
    - (Windows): **powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"**
- Restart your terminal
- Clone this repo into a working directory, e.g. **C:\work**
- Change into the mq-mcp-server directory: **cd mq-mcp-server**
- Install dependencies: **uv add "mcp[cli]" httpx**
- Open **mqmcpserver.py** in your editor of choice and change:
    - URL_BASE to point to the base URL of your mqweb server
    - USER_NAME and PASSWORD to the username and password of the user you want to run MQSC commands as. Bear in mind that if the user is a member of the MQWebAdmin or MQWebUser roles then requests to the MQ MCP server will be able to change your MQ configuration, so you might only want to use these roles in a test environment
- Save your changes
- Start the MQ MCP server by running: **uv run mqmcpserver.py**

By default the MQ MCP server will be listening on http://127.0.0.1:8000/mcp using the streamable HTTP protocol. You can adjust the host name and port number, or use a different protocol using the information provided [here](https://github.com/jlowin/fastmcp#running-your-server).
Some alternatives are included, with comments, in the code.

## Connecting the MCP server to an LLM

Follow the instructions provided by your LLM for connecting to your new MCP server. For example you could connect to it using [IBM Bob](https://www.ibm.com/products/bob) or [IBM Watsonx Orchestrate](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=servers-importing-tools-from-mcp-server). 
Alternatively, a [wide range](https://modelcontextprotocol.io/clients) of other LLMs support MCP.

