"""MCP Agent — Orchestrates LLM + Tool Calling.
The LLM decides which tools to call, the agent executes them,
feeds results back, and generates a final answer.

This is the agentic loop:
    1. User asks a question
    2. LLM sees available tools + RAG context
    3. LLM decides: answer directly OR call a tool
    4. If tool called → execute → feed result back to LLM
    5. LLM generates final answer with tool results
    6. Repeat if LLM wants to call another tool (max 3 iterations)
"""
import json
from typing import Optional
from discovery.engine.llm_client import get_llm
from discovery.engine.mcp.tools import get_tool_definitions, execute_tool, TOOLS
from discovery.engine.rag.retriever import get_retriever


MAX_TOOL_ITERATIONS = 3

AGENT_SYSTEM_PROMPT = """You are Ontika, an intelligent data operations agent for the BT Data Fabric platform.
You can answer questions about the data estate AND take actions on it.

You have access to these tools:
{tool_descriptions}

AVAILABLE BIGQUERY TABLES (Gold / Data Products):
- bt-df-lkhouse.lakehouse_dataproduct.loan_eligibility_360
- bt-df-lkhouse.lakehouse_dataproduct.customer_spend_360
- bt-df-lkhouse.lakehouse_dataproduct.customer_health_score
- bt-df-lkhouse.lakehouse_dataproduct.collections_priority
- bt-df-lkhouse.lakehouse_dataproduct.fraud_risk_indicators
- bt-df-lkhouse.lakehouse_dataproduct.pipeline_monitor
- bt-df-lkhouse.eastside_dataproduct.pos_transactions
- bt-df-lkhouse.eastside_dataproduct.online_orders
- bt-df-lkhouse.eastside_dataproduct.customer_profiles
- bt-df-lkhouse.eastside_dataproduct.product_catalogue
- bt-df-lkhouse.eastside_dataproduct.returns_exchanges
- bt-df-lkhouse.eastside_dataproduct.inventory_movements
- bt-df-lkhouse.eastside_dataproduct.supplier_purchase_orders
- bt-df-lkhouse.eastside_dataproduct.store_staff

When the user asks to query a table, use the query_table tool with a full SQL statement.
Always use backtick-quoted table names: `bt-df-lkhouse.lakehouse_dataproduct.table_name`
If the user says a table name without the dataset, infer it from the list above.

RULES:
- Always use tools when you need real data (don't guess numbers)
- For destructive actions (trigger_pipeline), always confirm with the user first
- Be concise and specific in your answers
- If a tool returns an error, explain what went wrong and suggest alternatives
- When returning query results, format them as a markdown table

To call a tool, respond with EXACTLY this JSON format (nothing else):
{{"tool_call": {{"name": "<tool_name>", "arguments": {{...}}}}}}

If you have enough information to answer without a tool, just respond normally.
If you've received tool results and can now answer, respond with the final answer (no more tool calls).

CONTEXT FROM KNOWLEDGE BASE:
{rag_context}
"""


class MCPAgent:
    """Agentic LLM with tool-calling capability."""

    def __init__(self):
        self.llm = get_llm()
        self.retriever = get_retriever()

    def run(self, user_message: str) -> str:
        """Run the agentic loop: question → (tool calls) → answer."""

        # Get RAG context
        rag_context = ""
        if self.retriever.is_available:
            rag_context = self.retriever.get_context_for_prompt(user_message, max_chars=2000)

        # Build tool descriptions
        tool_desc = "\n".join(
            f"- {t['name']}: {t['description']}"
            for t in TOOLS
        )

        # System prompt with tools + RAG context
        system = AGENT_SYSTEM_PROMPT.format(
            tool_descriptions=tool_desc,
            rag_context=rag_context or "(No indexed context available. Use tools to fetch data.)",
        )

        # Conversation history for this turn
        messages = [{"role": "user", "content": user_message}]
        tool_results = []

        for iteration in range(MAX_TOOL_ITERATIONS):
            # Build the full user message including tool results
            if tool_results:
                context = "\n\n".join(
                    f"[Tool result from {tr['tool']}]:\n{tr['result']}"
                    for tr in tool_results
                )
                full_user = f"{user_message}\n\n--- Tool Results ---\n{context}\n\nNow answer the original question using the tool results above."
            else:
                full_user = user_message

            # Call LLM
            response = self.llm.generate(
                system=system,
                user=full_user,
                max_tokens=1024,
                temperature=0.1,
            )

            if not response or response == "__QUOTA_EXCEEDED__":
                return "I'm unable to process that right now. The LLM service is unavailable."

            # Check if LLM wants to call a tool
            tool_call = self._parse_tool_call(response)

            if tool_call:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})

                # Execute the tool
                result = execute_tool(tool_name, tool_args)
                tool_results.append({"tool": tool_name, "result": result})

                # Continue the loop — LLM will see the result next iteration
                continue
            else:
                # LLM responded with a final answer (no tool call)
                return response

        # Max iterations reached — return what we have
        if tool_results:
            return response or "I gathered some data but couldn't formulate a complete answer. Here's what I found:\n\n" + \
                "\n".join(f"**{tr['tool']}**: {tr['result'][:200]}" for tr in tool_results)

        return response or "I wasn't able to answer that. Try rephrasing or ask about a specific table."

    def _parse_tool_call(self, response: str) -> Optional[dict]:
        """Parse a tool call from LLM response."""
        # Look for JSON tool_call pattern
        response = response.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(response)
            if "tool_call" in parsed:
                return parsed["tool_call"]
        except json.JSONDecodeError:
            pass

        # Try to find JSON within the response
        import re
        json_match = re.search(r'\{["\s]*tool_call["\s]*:', response)
        if json_match:
            try:
                # Extract from the match to end
                json_str = response[json_match.start():]
                # Find matching closing brace
                depth = 0
                for i, c in enumerate(json_str):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            parsed = json.loads(json_str[:i + 1])
                            return parsed.get("tool_call")
            except (json.JSONDecodeError, IndexError):
                pass

        return None


# Singleton
_agent: Optional[MCPAgent] = None


def get_agent() -> MCPAgent:
    global _agent
    if _agent is None:
        _agent = MCPAgent()
    return _agent
