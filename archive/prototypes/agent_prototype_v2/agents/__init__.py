"""
Agent Infrastructure Module

Core utilities for all agents including LLM interaction through LiteLLM
with Langfuse monitoring (v3.x).
"""

from dotenv import load_dotenv
load_dotenv()

from litellm import completion
from langfuse import Langfuse
import logging
import json
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Initialize Langfuse client
langfuse = Langfuse()


def call_llm(
    messages: List[Dict[str, str]], 
    agent_name: str = "default",
    model: str = "anthropic/claude-sonnet-4-20250514",
    temperature: float = 0.7,
    response_format: Optional[Dict[str, str]] = None
) -> str:
    """
    Execute LLM completion with Langfuse tracking.
    
    Args:
        messages: OpenAI-format message list
        agent_name: Agent identifier
        model: LLM model
        temperature: Sampling temperature
        response_format: Optional format specification
        
    Returns:
        Generated text response
    """
    # Create trace for this LLM call
    trace = langfuse.trace(
        name=f"{agent_name}_execution",
        metadata={
            "agent": agent_name,
            "model": model,
            "temperature": temperature
        },
        tags=[agent_name, model]
    )
    
    api_params = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    
    if response_format:
        api_params["response_format"] = response_format
    
    try:
        # Create generation span
        generation = trace.generation(
            name=f"{agent_name}_llm_call",
            model=model,
            input=messages,
            metadata={"temperature": temperature}
        )
        
        # Call LLM
        response = completion(**api_params)
        result = response.choices[0].message.content
        
        # End generation with output
        generation.end(output=result)
        
        logger.info(f"{agent_name} LLM call completed")
        
        return result
        
    except Exception as e:
        logger.error(f"LLM call failed for {agent_name}: {str(e)}")
        trace.update(metadata={"error": str(e)})
        raise


def parse_llm_json(response: str) -> Dict[str, Any]:
    """
    Extract and parse JSON from LLM response.
    
    Args:
        response: Raw text response
        
    Returns:
        Parsed JSON dictionary
    """
    # Strategy 1: Extract from markdown code blocks
    json_match = re.search(r'```json\s*\n(.*?)\n```', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Strategy 2: Generic code blocks
    code_match = re.search(r'```\s*\n(.*?)\n```', response, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Strategy 3: Parse entire response
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass
    
    # Strategy 4: Find JSON object
    json_object_match = re.search(r'\{.*\}', response, re.DOTALL)
    if json_object_match:
        try:
            return json.loads(json_object_match.group(0))
        except json.JSONDecodeError:
            pass
    
    logger.warning("Could not parse JSON from LLM response")
    return {"raw_response": response, "parse_error": True}


def validate_json_schema(data: Dict[str, Any], required_keys: List[str]) -> bool:
    """
    Validate that parsed JSON contains required keys.
    
    Args:
        data: Parsed JSON dictionary
        required_keys: List of required keys
        
    Returns:
        True if valid
    """
    return all(key in data for key in required_keys)