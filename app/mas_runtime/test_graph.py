"""Quick test of the LangGraph system."""

from graph import run_agent

# Test simple conversational query
print("Test 1: Conversational")
result = run_agent("Hello!", verbose=True)

print("\n" + "="*60 + "\n")

# Test data request
print("Test 2: Data Request")
result2 = run_agent("What were Arsenal's points in 2023_2024?", verbose=False)
print(f"Final Response: {result2.get('final_response', 'N/A')}")
