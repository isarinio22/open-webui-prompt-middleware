from fastapi import APIRouter, Request

from app.schemas import ModelList, ModelObject

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request) -> ModelList:
    allowed: list[str] = request.app.state.settings.allowed_models
    return ModelList(data=[ModelObject(id=model_id) for model_id in allowed])
