import atexit
import logging
import os
import sys
import termios
from typing import List, Union

from rich.highlighter import ReprHighlighter
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.logging import TextualHandler
from textual.widgets import Footer, Header, Markdown, Tree
from textual.widgets.tree import TreeNode

import copick
from copick.models import (
    CopickFeatures,
    CopickMesh,
    CopickObject,
    CopickPicks,
    CopickRoot,
    CopickRun,
    CopickSegmentation,
    CopickTomogram,
    CopickVoxelSpacing,
)
from copick.ops._markdown import ENTITY_TO_MD

logging.basicConfig(
    level="DEBUG",
    handlers=[TextualHandler()],
)

_copick_types = Union[
    CopickRoot,
    CopickRun,
    CopickVoxelSpacing,
    CopickTomogram,
    CopickFeatures,
    CopickSegmentation,
    CopickMesh,
    CopickPicks,
    CopickObject,
]


# Emoji icons for different entities
ICONS = {
    "root": "🗂",  # Card Index Dividers
    "run": "🏃",  # Runner
    "voxel_spacing": "📏",  # Ruler
    "tomogram": "🧊",  # Ice Cube
    "feature": "🔢",  # Input Numbers
    "pick": "📍",  # Round Pushpin
    "mesh": "🕸",  # Spider Web
    "segmentation": "🖌",  # Paint Brush
    "object": "🦠",  # Microbe
    "folder": "📁",  # File Folder
}


def copick_to_label(entity: _copick_types, include_metadata: bool = True) -> Text:
    """
    Convert a Copick entity to a rich Text label.

    Args:
        entity: The Copick entity to convert.
        include_metadata: Whether to include metadata in the label.

    Returns:
        Text label.
    """
    pass


class CopickTreeApp(App):
    DEFAULT_CSS = """
       Tree {
           width: 2fr; /* 75% of the space */
       }
       Markdown {
           width: 1fr; /* 25% of the space */
       }
       """
    TITLE = "Copick Browser"
    # TODO: Add key bindings for search and other actions
    # BINDINGS = [
    #     ("^f", "search", "Search Runs"),
    # ]

    def __init__(self, copick_root: CopickRoot):
        """
        Initialize the CopickTreeApp.

        Args:
            copick_root: The CopickRoot object to browse.
        """
        super().__init__()
        self.copick_root = copick_root
        self.node_data = {}  # Dictionary to store node data
        self.markdown = None


    def on_mount(self) -> None:
        """Initialize the tree with the root node."""
        pass

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """
        Handle the tree node expanded event to load data lazily.

        Args:
            event: The event object containing the node that was expanded.
        """
        pass

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """
        Handle the tree node highlighted event to display data.

        Args:
            event: The event object containing the node that was highlighted.
        """
        pass

    def add_object_folder_node(self, root_node: TreeNode, objects: List[CopickObject]) -> None:
        """
        Add parent node for objects to the root node.

        Args:
            root_node: The root node of the tree.
            objects: The list of Copick objects to add.
        """
        pass

    def add_object_data_node(self, objects_node: TreeNode, objects: List[CopickObject]) -> None:
        """
        Add objects nodes to the objects folder node.

        Args:
            objects_node: The objects node to add the data to.
            objects: The list of Copick objects to add.
        """
        pass

    def add_runs_node(self, root_node: TreeNode) -> None:
        """
        Add runs nodes to the root node.

        Args:
            root_node: The root node of the tree.
        """
        pass

    def add_run_data_nodes(self, run_node: TreeNode, run: CopickRun) -> None:
        """
        Add voxel spacings, picks, meshes, and segmentations nodes to the run node.

        Args:
            run_node: The run node to add the data to.
            run: The CopickRun object to add.
        """
        pass

    def add_voxel_spacing_parent_nodes(
        self,
        voxel_parent_node: TreeNode,
        voxel_spacings: List[CopickVoxelSpacing],
    ) -> None:
        """
        Add tomograms nodes to the voxel spacing node.

        Args:
            voxel_parent_node: The voxel parent node to add the data to.
            voxel_spacings: The list of CopickVoxelSpacing objects to add.
        """
        pass

    def add_tomogram_data_nodes(self, voxel_node: TreeNode, tomograms: List[CopickTomogram]) -> None:
        """
        Add tomogram node to the voxel parent node.

        Args:
            voxel_node: The voxel node to add the tomograms to.
            tomograms: The list of CopickTomogram objects to add.
        """
        pass

    def add_features_data_nodes(self, tomogram_node: TreeNode, features: List[CopickFeatures]) -> None:
        """
        Add features node to the tomogram node.

        Args:
            tomogram_node (TreeNode): The tomogram node to add the features to.
            features (list[CopickFeatures]): The list of features to add.
        """
        pass

    def add_segmentation_data_nodes(
        self,
        segmentation_parent_node: TreeNode,
        segmentations: List[CopickSegmentation],
    ) -> None:
        """
        Add segmentations to the segmentation parent node.

        Args:
            segmentation_parent_node (TreeNode): The segmentation parent node to add the segmentations to.
            segmentations (list[CopickSegmentation]): The list of segmentations to add.
        """
        pass

    def add_mesh_data_nodes(
        self,
        mesh_parent_node: TreeNode,
        meshes: List[CopickMesh],
    ) -> None:
        """
        Add meshes to the mesh parent node.

        Args:
            mesh_parent_node (TreeNode): The mesh parent node to add the meshes to.
            meshes (list[CopickMesh]): The list of meshes to add.
        """
        pass

    def add_picks_data_nodes(
        self,
        picks_parent_node: TreeNode,
        picks: List[CopickPicks],
    ) -> None:
        """
        Add picks to the picks parent node.

        Args:
            picks_parent_node (TreeNode): The picks parent node to add the picks to.
            picks (list[CopickPicks]): The list of picks to add.
        """
        pass


def launch_app(
    config_path: str = None,
    dataset_ids: List[int] = None,
    copick_root: CopickRoot = None,
):
    """
    Launch the Copick Tree App.

    Args:
        config_path: Path to the configuration file.
        dataset_ids: List of dataset IDs to include in the project.
    """
    if config_path:
        copick_root = copick.from_file(config_path)
    elif dataset_ids:
        copick_root = copick.from_czcdp_datasets(dataset_ids, "/tmp/overlay")
    elif copick_root:
        pass
    else:
        raise ValueError("Either config_path or dataset_ids must be provided.")


    atexit.register(reset_terminal)

    logging.basicConfig(level=logging.ERROR)

    CopickTreeApp(copick_root).run()


if __name__ == "__main__":
    copick_root = copick.from_czcdp_datasets([10440], "/tmp/overlay")

    launch_app(copick_root=copick_root)
