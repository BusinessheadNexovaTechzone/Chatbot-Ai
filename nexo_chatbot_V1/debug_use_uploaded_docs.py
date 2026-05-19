import asyncio
from app.models.schemas import ChatRequest
from app.services.orchestrator import orchestrator

async def run_test():
    try:
        req = ChatRequest(
            query='ceo',
            session_id='string',
            stream=False,
            assistant_name='Assistant',
            use_uploaded_docs=False,
        )
        resp = await orchestrator.handle(req)
        print(resp)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(run_test())
