"""A shared brand treatment and distinct visual ideas, chosen before product vision."""
from difflib import SequenceMatcher
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class CampaignIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    typography: str = Field(min_length=10, max_length=500)
    art_direction: str = Field(min_length=10, max_length=500)
    palette: list[Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]] = Field(min_length=1, max_length=3)


class VisualConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: Literal["product_hero", "human_moment", "ingredient_story", "detail_study", "graphic_story", "overhead_arrangement"]
    scene: str = Field(min_length=20, max_length=700)
    camera: Literal["eye_level", "overhead", "low_angle", "close_up", "wide_environment"]
    composition: Literal["asymmetric_editorial", "diagonal_motion", "central_sculptural", "split_comparison", "immersive_crop", "overhead_grid"]
    visual_hook: str = Field(min_length=20, max_length=500)
    background_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ProductObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(min_length=10, max_length=700)
    # Scenery is recorded only as exclusions. It must not become art direction.
    source_scene_to_discard: list[Annotated[str, Field(min_length=3, max_length=120)]] = Field(min_length=1, max_length=8)


def normalized(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def validate_visual_variety(posts):
    """Reject repeated camera/layout systems even when the copy or title changes."""
    for index, post in enumerate(posts):
        concept = post.visual_concept
        for previous in posts[:index]:
            other = previous.visual_concept
            axes = sum(getattr(concept, key) != getattr(other, key) for key in ("route", "camera", "composition"))
            if concept.route == other.route or axes < 2:
                raise ValueError("Each post needs a different visual route and at least one different camera or composition.")
            if SequenceMatcher(None, normalized(concept.scene), normalized(other.scene)).ratio() > .82:
                raise ValueError("The week's scenes repeat; changing the headline is not a new design idea.")


def repeats_image_prompt(current, previous):
    """Copy changes alone must not pass as a different image-generation prompt."""
    def without_copy(direction):
        text = normalized(direction["image_prompt"])
        for field in ("headline", "cta"):
            text = text.replace(normalized(direction[field]), " ")
        return " ".join(text.split())
    return SequenceMatcher(None, without_copy(current), without_copy(previous)).ratio() > .88
