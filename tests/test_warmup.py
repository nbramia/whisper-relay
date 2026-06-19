import pytest

from voice_gateway.turns import TurnPipeline


@pytest.mark.asyncio
async def test_pipeline_warmup(pipeline: TurnPipeline):
    await pipeline.warmup()
