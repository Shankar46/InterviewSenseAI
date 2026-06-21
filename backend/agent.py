from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from backend.career_assistant import generate_career_plan as run_agent

# Vercel looks for this exact 'app' variable name
app = FastAPI()

# Define the structure of your incoming frontend payload
class AgentRequest(BaseModel):
    message: str

@app.get("/api/agent")
def health_check():
    return {"status": "InterviewSense AI Agent Endpoint Active"}

@app.post("/api/agent")
def handle_agent(payload: AgentRequest):
    try:
        # Call your core function with the parsed message string
        result = run_agent(payload.message)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Keep your alias definitions intact for backwards compatibility
__all__ = ["run_agent", "app"]