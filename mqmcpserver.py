#
# Copyright (c) 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import httpx
import json

from typing import Any
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("mqmcpserver")

# Change this to point to your mqweb server
URL_BASE = "https://localhost:9443/ibmmq/rest/v3/admin/"

# Change these to a suitable user in your mqweb server
USER_NAME = "mqreader"
PASSWORD = "mqreader"

@mcp.tool()
async def dspmq() -> str:
    """List available queue managers and whether they are running or not
    """
    headers = {
        "Content-Type": "application/json",
        "ibm-mq-rest-csrf-token": "token"
    }    
    
    url = URL_BASE + "qmgr/"

    auth = httpx.BasicAuth(username=USER_NAME, password=PASSWORD)
    async with httpx.AsyncClient(verify=False,auth=auth) as client:
        try:            
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return prettify_dspmq(response.content)
        except Exception as err:
            print(err)
            return "Something went wrong!"
                        
# Put the output of for each queue manager on its own line, separated by ---                        
def prettify_dspmq(payload: str) -> str:
    jsonOutput = json.loads(payload.decode("utf-8"))
    prettifiedOutput="\n---\n"
    for x in jsonOutput['qmgr']:
      prettifiedOutput += "name = " + x['name'] + ", running = " + x['state'] + "\n---\n"
    
    return prettifiedOutput
    
@mcp.tool()
async def runmqsc(qmgr_name: str, mqsc_command: str) -> str:
    """Run an MQSC command against a specific queue manager

    Args:
        qmgr_name: A queue manager name   
        mqsc_command: An MQSC command to run on the queue manager   
    """
    headers = {
        "Content-Type": "application/json",
        "ibm-mq-rest-csrf-token": "a"
    }
    
    data = "{\"type\":\"runCommand\",\"parameters\":{\"command\":\"" + mqsc_command + "\"}}"
    
    url = URL_BASE + "action/qmgr/" + qmgr_name + "/mqsc"

    auth = httpx.BasicAuth(username=USER_NAME, password=PASSWORD)
    async with httpx.AsyncClient(verify=False,auth=auth) as client:
        try:            
            response = await client.post(url, data=data, headers=headers, timeout=30.0)
            response.raise_for_status()
            return prettify_runmqsc(response.content)
        except Exception as err:
            print(err)
            return "Something went wrong!"
            
# Put the output of each MQSC command on its own line, separated by ---
# Deals with both z/OS and distributed queue managers
def prettify_runmqsc(payload: str) -> str:
    jsonOutput = json.loads(payload.decode("utf-8"))
    prettifiedOutput="\n---\n"
    for x in jsonOutput['commandResponse']:
        # z/OS
        if x['text'][0].startswith("CSQN205I"):
            # Remove leading and trailing messages, as they aren't needed. 
            x['text'].pop(0)            
            x['text'].pop()
            for y in x['text']:
                prettifiedOutput += y[15:] + "\n---\n"            
        # Distributed
        else:        
            prettifiedOutput += x['text'][0] + "\n---\n"   
    
    return prettifiedOutput    

if __name__ == "__main__":
    # Initialize and run the server on http://127.0.0.1:8000/mcp
    mcp.run(transport='streamable-http')
    # If using IBM Bob then use one of these
    #mcp.run(transport='stdio')
    # URL is http://127.0.0.1:8000/sse
    #mcp.run(transport='sse')