import os
import argparse
from src.agents import Reasoning_Agent, LLM_Agent
from src.lean_runner import execute_lean_code
from typing import Dict, List, Tuple
import re # Added for parsing

type LeanCode = Dict[str, str]

def parse_code_proof(response: str) -> Tuple[str, str]:
    """Parses the LLM response to extract code and proof sections."""
    # First try to extract based on CODE: and PROOF: markers
    code_match = re.search(r"CODE:(.*?)(?:PROOF:|$)", response, re.DOTALL | re.IGNORECASE)
    proof_match = re.search(r"PROOF:(.*)", response, re.DOTALL | re.IGNORECASE)
    
    code = code_match.group(1).strip() if code_match else ""
    proof = proof_match.group(1).strip() if proof_match else ""
    
    # Remove markdown code blocks and language specifiers
    code = re.sub(r"```(?:lean)?\s*", "", code)
    code = re.sub(r"\s*```", "", code)
    proof = re.sub(r"```(?:lean)?\s*", "", proof)
    proof = re.sub(r"\s*```", "", proof)
    
    # Remove any function definition lines like "def function_name ..."
    code = re.sub(r"^def\s+\w+\s*\(.*\)\s*:.*:=\s*", "", code, flags=re.MULTILINE)
    
    # Normalize Lean's dot notation and bullet points
    # Convert dots and bullets to standard syntax
    proof = re.sub(r"^\s*[·•]\s*", "· ", proof, flags=re.MULTILINE)
    proof = re.sub(r"^\s*\.\s*", "· ", proof, flags=re.MULTILINE)
    
    # Default to "sorry" if parsing fails or result is empty
    if not code:
        code = "sorry"
    if not proof:
        proof = "sorry"
    
    return code, proof

def main_workflow(problem_description: str, task_lean_code: str = "") -> LeanCode:
    """
    Main workflow for the coding agent. This workflow takes in the problem description in natural language (description.txt) 
    and the corresponding Lean code template (task.lean). It returns the function implementation and the proof in Lean.
    
    Args:
        problem_description: Problem description in natural language. This file is read from "description.txt"
        task_lean_code: Lean code template. This file is read from "task.lean"
    
    Returns:
        LeanCode: Final generated solution, which is a dictionary with two keys: "code" and "proof".
    """
    generated_function_implementation = "sorry"
    generated_proof = "sorry"
    max_retries = 3
    retries = 0

    # Initialize the LLM agent (using GPT-4o as recommended for quality)
    agent = LLM_Agent(model="gpt-4o")

    # Extract the function name and type from the task template to provide context to the LLM
    function_match = re.search(r"def\s+(\w+)\s*\((.*?)\)\s*:(.*?):=", task_lean_code, re.DOTALL)
    function_name = function_match.group(1) if function_match else "function"
    function_args = function_match.group(2) if function_match else "args"
    function_return = function_match.group(3) if function_match else "return_type"
    
    # Extract the specification to provide as context
    spec_match = re.search(r"-- << SPEC START >>(.*?)-- << SPEC END >>", task_lean_code, re.DOTALL)
    specification = spec_match.group(1).strip() if spec_match else ""
    
    # Construct the initial prompt
    system_prompt = """You are an expert Lean 4 programmer.
Your task is to complete a Lean code template by providing only the implementation and proof.
DO NOT redefine the function or theorem. Just provide the body of the implementation and proof.

The template uses {{code}} and {{proof}} placeholders. I need:
1. ONLY the code to replace {{code}} - just the implementation body
2. ONLY the proof to replace {{proof}} - just the proof body

For proofs, remember:
- Don't use period (.) or bullet points like (· or •) at the beginning of lines in the proof
- For most simple cases, use 'simp' or 'rfl' tactics
- For cases that need analysis, use:
  cases h : expr with
  | case1 => ... 
  | case2 => ...
- Don't use 'focus' or 'by' in your proofs
- Always ensure your proof has no unexpected syntax

Format your answer EXACTLY like this:
CODE:
[your implementation code only]
PROOF:
[your proof only]
"""
    
    # Examples of successful proofs to help guide the LLM
    example_proofs = """
Example 1:
Function: def ident (x : Nat) : Nat
Specification: result = x
CODE: x
PROOF: rfl

Example 2:
Function: def isDivisibleBy11 (n : Int) : Bool
Specification: n % 11 = 0
CODE: n % 11 = 0
PROOF: simp

Example 3:
Function: def multiply (a b : Int) : Int
Specification: result = a * b
CODE: a * b
PROOF: rfl

Example 4:
Function: def cubeSurfaceArea (size : Int) : Int
Specification: result = 6 * size * size
CODE: 6 * size * size
PROOF: rfl
"""
    
    user_prompt = f"""Problem Description:
{problem_description}

Lean Code Template:
```lean
{task_lean_code}
```

For the function '{function_name}', I need:
1. The implementation code to replace {{code}}
2. The proof to replace {{proof}}

The specification is:
```lean
{specification}
```

Here are some examples of successful implementations and proofs:
{example_proofs}

DO NOT include:
- Function definitions (def ...)
- Theorem definitions (theorem ...)
- Any imports
- Just provide the exact code and proof bodies.

Remember to format your answer using CODE: and PROOF: markers.
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    while retries < max_retries:
        print(f"Attempt {retries + 1}/{max_retries}...")
        # Get response from the LLM agent
        response = agent.get_response(messages)
        print("LLM Response received.")
        #print(f"Raw LLM Response:\\n{response}") # Optional: for debugging

        # Parse the response
        generated_function_implementation, generated_proof = parse_code_proof(response)
        print(f"Parsed Code: {generated_function_implementation}")
        print(f"Parsed Proof: {generated_proof}")

        # Verify the generated code and proof
        temp_lean_code = task_lean_code.replace("{{code}}", generated_function_implementation)
        temp_lean_code = temp_lean_code.replace("{{proof}}", generated_proof)

        print("Verifying generated solution with Lean...")
        verification_result = execute_lean_code(temp_lean_code)
        print(f"Verification Result: {verification_result}")

        if "Lean code executed successfully." in verification_result:
            print("Solution verified successfully!")
            break # Exit loop if successful
        elif "sorry" in generated_function_implementation or "sorry" in generated_proof:
            print("Warning: LLM generated 'sorry'. Asking for a non-trivial solution.")
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "Your solution contains 'sorry'. Please provide a complete implementation and proof without using 'sorry'. Just provide the exact code and proof body that should replace {{code}} and {{proof}} respectively."})
        else:
            print("Verification failed. Asking LLM for correction...")
            # Add assistant's response and user's feedback for the next iteration
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": f"""Your solution had errors:
{verification_result}

Please fix the code and proof. Remember:
1. ONLY provide the exact body for {{code}} and {{proof}}
2. Do not include function definitions or extra formatting
3. Avoid using dots (.) at the beginning of lines in the proof
4. Do not use nested syntax like 'by_cases h' inside a case
5. Use simple proof tactics like 'simp', 'rfl', 'exact', etc."""})

        retries += 1
        if retries == max_retries:
            print(f"Max retries ({max_retries}) reached. Returning last generated solution.")

    # Return the final generated solution
    return {
        "code": generated_function_implementation,
        "proof": generated_proof
    }

def get_problem_and_code_from_taskpath(task_path: str) -> Tuple[str, str]:
    """
    Reads a directory in the format of task_id_*. It will read the file "task.lean" and also read the file 
    that contains the task description, which is "description.txt".
    
    After reading the files, it will return a tuple of the problem description and the Lean code template.
    
    Args:
        task_path: Path to the task file
    """
    problem_description = ""
    lean_code_template = ""
    
    with open(os.path.join(task_path, "description.txt"), "r") as f:
        problem_description = f.read()

    with open(os.path.join(task_path, "task.lean"), "r") as f:
        lean_code_template = f.read()

    return problem_description, lean_code_template

def get_unit_tests_from_taskpath(task_path: str) -> List[str]:
    """
    Reads a directory in the format of task_id_*. It will read the file "tests.lean" and return the unit tests.
    """
    with open(os.path.join(task_path, "tests.lean"), "r") as f:
        unit_tests = f.read()
    
    return unit_tests

def get_task_lean_template_from_taskpath(task_path: str) -> str:
    """
    Reads a directory in the format of task_id_*. It will read the file "task.lean" and return the Lean code template.
    """
    with open(os.path.join(task_path, "task.lean"), "r") as f:
        task_lean_template = f.read()
    return task_lean_template