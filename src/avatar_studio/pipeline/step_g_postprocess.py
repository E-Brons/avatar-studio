"""Stage G — post-processing: circle frame overlay."""

import logging

from avatar_studio.pipeline.step_d_make_abbreviation import apply_circle_frame

logger = logging.getLogger(__name__)

__all__ = ["apply_circle_frame"]
