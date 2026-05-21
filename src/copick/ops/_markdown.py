from copick.impl.cryoet_data_portal import (
    CopickPicksCDP,
    CopickRootCDP,
    CopickRunCDP,
    CopickSegmentationCDP,
    CopickTomogramCDP,
)
from copick.impl.filesystem import CopickRootFSSpec, CopickRunFSSpec
from copick.impl.mlcroissant import CopickRootMLC, CopickRunMLC
from copick.models import (
    CopickFeatures,
    CopickMesh,
    CopickPicks,
    CopickRoot,
    CopickRun,
    CopickSegmentation,
    CopickTomogram,
    CopickVoxelSpacing,
    PickableObject,
)

DEFAULT_MARKDOWN = """\
# Metadata
"""

LOCAL_PROJECT = """\
# Local Copick Project

|
"""


def object_to_md(pickable_object: PickableObject) -> str:
    """Convert the PickableObject object to a markdown string."""
    pass


def root_to_md(root: CopickRoot) -> str:
    """Convert the CopickRoot object to a markdown string."""
    pass


def run_to_md(run: CopickRun) -> str:
    """Convert the CopickRun object to a markdown string."""
    pass


def voxel_spacing_to_md(voxel_spacing: CopickVoxelSpacing) -> str:
    """Convert the CopickVoxelSpacing object to a markdown string."""
    pass


def tomogram_to_md(tomogram: CopickTomogram) -> str:
    """Convert the tomogram object to a markdown string."""
    pass


def features_to_md(features: CopickFeatures) -> str:
    """Convert the features object to a markdown string."""
    pass


def segmentation_to_md(segmentation: CopickSegmentation) -> str:
    """Convert the segmentation object to a markdown string."""
    pass


def picks_to_md(picks: CopickPicks) -> str:
    """Convert the picks object to a markdown string."""
    pass


def mesh_to_md(mesh: CopickMesh) -> str:
    """Convert the mesh object to a markdown string."""
    pass


ENTITY_TO_MD = {
    "root": root_to_md,
    "object": object_to_md,
    "run": run_to_md,
    "voxel_spacing": voxel_spacing_to_md,
    "tomogram": tomogram_to_md,
    "features": features_to_md,
    "segmentation": segmentation_to_md,
    "picks": picks_to_md,
    "mesh": mesh_to_md,
}
