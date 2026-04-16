from openai import OpenAI
import json
from typing import Dict, Any

class LocalLLM:
    """
    Connector for a local AI (Ollama, LM Studio, etc.).
    Forces the AI to respond with structured JSON.
    """
    def __init__(self, 
                 base_url="http://localhost:11434/v1", # Default Ollama port
                 model="llama3"):                      # Replace with your local model
        
        # api_key is required by the library, but ignored by local servers
        self.client = OpenAI(base_url=base_url, api_key="local-ai")
        self.model = model

    def ask_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """
        Sends a prompt to the local AI and expects to receive a JSON dictionary.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                # Forces JSON mode (supported by recent Ollama and LM Studio versions)
                response_format={"type": "json_object"},
                temperature=0.2 # Low temperature for logical decisions
            )
            
            raw_content = response.choices[0].message.content
            return json.loads(raw_content)
            
        except json.JSONDecodeError:
            raise ValueError(f"The AI did not return valid JSON: {raw_content}")
        except Exception as e:
            raise RuntimeError(f"Error communicating with local AI: {str(e)}")