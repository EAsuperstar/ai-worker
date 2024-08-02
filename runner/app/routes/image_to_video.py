import logging
import os
import random
from typing import Annotated

from app.dependencies import get_pipeline
from app.pipelines.base import Pipeline
from app.routes.util import (HTTPError, VideoResponse, http_error,
                             image_to_data_url)
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

router = APIRouter()

logger = logging.getLogger(__name__)

RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {"model": HTTPError},
    status.HTTP_401_UNAUTHORIZED: {"model": HTTPError},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": HTTPError},
}


# TODO: Make model_id and other None properties optional once Go codegen tool supports
# OAPI 3.1 https://github.com/deepmap/oapi-codegen/issues/373
@router.post("/image-to-video", response_model=VideoResponse, responses=RESPONSES)
@router.post(
    "/image-to-video/",
    response_model=VideoResponse,
    responses=RESPONSES,
    include_in_schema=False,
)
async def image_to_video(
    image: Annotated[UploadFile, File(description="Image, numpy array or tensor representing an image batch to be used as the starting point. For both numpy array and pytorch tensor, the expected value range is between [0, 1] If it’s a tensor or a list or tensors, the expected shape should be (B, C, H, W) or (C, H, W). If it is a numpy array or a list of arrays, the expected shape should be (B, H, W, C) or (H, W, C) It can also accept image latents as image, but if passing latents directly it is not encoded again.")],
    model_id: Annotated[str, Form(description="The huggingface model ID to run the inference on (i.e. SG161222/RealVisXL_V4.0_Lightning:)")] = "",
    height: Annotated[int, Form(description="The height in pixels of the generated image.")] = 576,
    width: Annotated[int, Form(description="The width in pixels of the generated image.")] = 1024,
    fps: Annotated[int, Form(description="the frames per second of the generated video.")] = 6,
    motion_bucket_id: Annotated[int, Form(description="the motion bucket id to use for the generated video. This can be used to control the motion of the generated video. Increasing the motion bucket id increases the motion of the generated video.")] = 127,
    noise_aug_strength: Annotated[float, Form(description="the amount of noise added to the conditioning image. The higher the values the less the video resembles the conditioning image. Increasing this value also increases the motion of the generated video.")] = 0.02,
    seed: Annotated[int, Form(description="The seed to set.")] = None,
    safety_check: Annotated[bool, Form(description="Classification module that estimates whether generated images could be considered offensive or harmful. Please refer to the model card for more details about a model’s potential harms.")] = True,
    num_inference_steps: Annotated[
        int, Form(description="The number of denoising steps. More denoising steps usually lead to a higher quality image at the expense of slower inference.")
    ] = 25,  # NOTE: Hardcoded due to varying pipeline values.
    pipeline: Pipeline = Depends(get_pipeline),
    token: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
):
    auth_token = os.environ.get("AUTH_TOKEN")
    if auth_token:
        if not token or token.credentials != auth_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
                content=http_error("Invalid bearer token"),
            )

    if model_id != "" and model_id != pipeline.model_id:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=http_error(
                f"pipeline configured with {pipeline.model_id} but called with "
                f"{model_id}"
            ),
        )

    if height % 8 != 0 or width % 8 != 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=http_error(
                f"`height` and `width` have to be divisible by 8 but are {height} and "
                f"{width}."
            ),
        )

    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    try:
        batch_frames, has_nsfw_concept = pipeline(
            image=Image.open(image.file).convert("RGB"),
            height=height,
            width=width,
            fps=fps,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            num_inference_steps=num_inference_steps,
            safety_check=safety_check,
            seed=seed,
        )
    except Exception as e:
        logger.error(f"ImageToVideoPipeline error: {e}")
        logger.exception(e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=http_error("ImageToVideoPipeline error"),
        )

    output_frames = []
    for frames in batch_frames:
        output_frames.append(
            [
                {
                    "url": image_to_data_url(frame),
                    "seed": seed,
                    "nsfw": has_nsfw_concept[0],
                }
                for frame in frames
            ]
        )

    return {"frames": output_frames}
