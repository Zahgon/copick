import concurrent.futures
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, Union

import zarr
from fsspec import AbstractFileSystem

from copick.impl.overlay import (
    CopickFeaturesOverlay,
    CopickMeshOverlay,
    CopickObjectOverlay,
    CopickPicksOverlay,
    CopickRunOverlay,
    CopickSegmentationOverlay,
    CopickTomogramOverlay,
    CopickVoxelSpacingOverlay,
)
from copick.models import (
    CopickConfig,
    CopickFeatures,
    CopickFeaturesMeta,
    CopickMeshMeta,
    CopickPicksFile,
    CopickRoot,
    CopickRunMeta,
    CopickSegmentationMeta,
    CopickTomogramMeta,
    CopickVoxelSpacingMeta,
    PickableObject,
)
from copick.util.log import get_logger

# Don't import Geometry at runtime to keep CLI snappy
if TYPE_CHECKING:
    from trimesh.parent import Geometry

logger = get_logger(__name__)


class CopickConfigFSSpec(CopickConfig):
    """Copick configuration for fsspec-based storage.

    Attributes:
        overlay_root (str): The root URL for the overlay storage.
        static_root (Optional[str]): The root URL for the static storage.
        overlay_fs_args (Optional[Dict[str, Any]]): Additional arguments for the overlay filesystem.
        static_fs_args (Optional[Dict[str, Any]]): Additional arguments for the static filesystem.
    """

    config_type: str = "filesystem"
    overlay_root: str
    static_root: Optional[str] = None

    overlay_fs_args: Optional[Dict[str, Any]] = {}
    static_fs_args: Optional[Dict[str, Any]] = {}


class CopickPicksFSSpec(CopickPicksOverlay):
    """CopickPicks class backed by fsspec storage.

    Attributes:
        path (str): The path to the picks file.
        directory (str): The directory containing the picks file.
        fs (AbstractFileSystem): The filesystem containing the picks file.
    """

    run: "CopickRunFSSpec"




    def _load(self) -> CopickPicksFile:
        if not self.fs.exists(self.path):
            logger.critical(f"File not found: {self.path}")
            raise FileNotFoundError(f"File not found: {self.path}")

        with self.fs.open(self.path, "r") as f:
            data = json.load(f)

        return CopickPicksFile(**data)

    def _store(self) -> None:
        if not self.fs.exists(self.directory):
            self.fs.makedirs(self.directory, exist_ok=True)

        with self.fs.open(self.path, "w") as f:
            json.dump(self.meta.model_dump(), f, indent=4)

    def _delete_data(self) -> None:
        if self.fs.exists(self.path):
            self.fs.rm(self.path)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickMeshFSSpec(CopickMeshOverlay):
    """CopickMesh class backed by fspec storage.

    Attributes:
        path (str): The path to the mesh file.
        directory (str): The directory containing the mesh file.
        fs (AbstractFileSystem): The filesystem containing the mesh file.
    """

    run: "CopickRunFSSpec"




    def _load(self) -> "Geometry":
        if not self.fs.exists(self.path):
            logger.critical(f"File not found: {self.path}")
            raise FileNotFoundError(f"File not found: {self.path}")

        with self.fs.open(self.path, "rb") as f:
            # Defer trimesh import to keep CLI snappy (trimesh imports scipy)
            import trimesh

            scene = trimesh.load(f, file_type="glb")

        return scene

    def _store(self):
        if not self.fs.exists(self.directory):
            self.fs.makedirs(self.directory, exist_ok=True)

        with self.fs.open(self.path, "wb") as f:
            _ = self._mesh.export(f, file_type="glb")

    def _delete_data(self) -> None:
        if self.fs.exists(self.path):
            self.fs.rm(self.path)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickSegmentationFSSpec(CopickSegmentationOverlay):
    """CopickSegmentation class backed by fsspec storage.

    Attributes:
        filename (str): The filename of the segmentation file.
        path (str): The path to the segmentation file.
        fs (AbstractFileSystem): The filesystem containing the segmentation file.
    """

    run: "CopickRunFSSpec"




    def zarr(self) -> zarr.storage.FSStore:
        """Get the zarr store for the segmentation object.

        Returns:
            zarr.storage.FSStore: The zarr store for the segmentation object.
        """
        if self.read_only:
            mode = "r"
            create = False
        else:
            mode = "w"
            create = not self.fs.exists(self.path)

        return zarr.storage.FSStore(
            self.path,
            fs=self.fs,
            mode=mode,
            key_separator="/",
            dimension_separator="/",
            create=create,
        )

    def _delete_data(self) -> None:
        # Remove the segmentation folder
        if self.fs.exists(self.path):
            self.fs.rm(self.path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickFeaturesFSSpec(CopickFeaturesOverlay):
    """CopickFeatures class backed by fsspec storage.

    Attributes:
        path (str): The path to the features file.
        fs (AbstractFileSystem): The filesystem containing the features file.
    """

    tomogram: "CopickTomogramFSSpec"



    def zarr(self) -> zarr.storage.FSStore:
        """Get the zarr store for the features object.

        Returns:
            zarr.storage.FSStore: The zarr store for the features object.
        """
        if self.read_only:
            mode = "r"
            create = False
        else:
            mode = "w"
            create = not self.fs.exists(self.path)

        return zarr.storage.FSStore(
            self.path,
            fs=self.fs,
            mode=mode,
            key_separator="/",
            dimension_separator="/",
            create=create,
        )

    def _delete_data(self) -> None:
        # Remove the features folder
        if self.fs.exists(self.path):
            self.fs.rm(self.path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickTomogramFSSpec(CopickTomogramOverlay):
    """CopickTomogram class backed by fsspec storage.

    Attributes:
        static_path (str): The path to the tomogram on the static source.
        overlay_path (str): The path to the tomogram on the overlay source.
        static_stem (str): The stem of the tomogram on the static source.
        overlay_stem (str): The stem of the tomogram on the overlay source.
        fs_static (AbstractFileSystem): The filesystem containing the tomogram on the static source.
        fs_overlay (AbstractFileSystem): The filesystem containing the tomogram on the overlay source.
        static_is_overlay (bool): Whether the static and overlay sources are the same.
    """

    voxel_spacing: "CopickVoxelSpacingFSSpec"

    def _feature_factory(self) -> Tuple[Type[CopickFeatures], Type["CopickFeaturesMeta"]]:
        return CopickFeaturesFSSpec, CopickFeaturesMeta










    def zarr(self) -> zarr.storage.FSStore:
        """Get the zarr store for the tomogram object.

        Returns:
            zarr.storage.FSStore: The zarr store for the tomogram object.
        """
        if self.read_only:
            fs = self.fs_static
            path = self.static_path
            mode = "r"
            create = False
        else:
            fs = self.fs_overlay
            path = self.overlay_path
            mode = "w"
            create = not fs.exists(path)

        return zarr.storage.FSStore(
            path,
            fs=fs,
            mode=mode,
            key_separator="/",
            dimension_separator="/",
            create=create,
        )

    def _delete_data(self) -> None:
        # Remove the tomogram folder
        if self.fs_overlay.exists(self.overlay_path):
            self.fs_overlay.rm(self.overlay_path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.overlay_path}")


class CopickVoxelSpacingFSSpec(CopickVoxelSpacingOverlay):
    """CopickVoxelSpacing class backed by fsspec storage.

    Attributes:
        static_path (str): The path to the voxel spacing on the static source.
        overlay_path (str): The path to the voxel spacing on the overlay source.
        fs_static (AbstractFileSystem): The filesystem containing the voxel spacing on the static source.
        fs_overlay (AbstractFileSystem): The filesystem containing the voxel spacing on the overlay source.
        static_is_overlay (bool): Whether the static and overlay sources are the same.

    """

    run: "CopickRunFSSpec"

    def _tomogram_factory(self) -> Tuple[Type[CopickTomogramFSSpec], Type[CopickTomogramMeta]]:
        return CopickTomogramFSSpec, CopickTomogramMeta








    def ensure(self, create: bool = False) -> bool:
        """Checks if the voxel spacing record exists in the static or overlay directory, optionally creating it in the
        overlay filesystem if it does not.

        Args:
            create: Whether to create the voxel spacing record if it does not exist.

        Returns:
            bool: True if the voxel spacing record exists, False otherwise.
        """
        if self.static_is_overlay:
            exists = self.fs_overlay.exists(self.overlay_path)
        else:
            exists = self.fs_static.exists(self.static_path) or self.fs_overlay.exists(self.overlay_path)

        if not exists and create:
            self.fs_overlay.makedirs(self.overlay_path, exist_ok=True)
            # TODO: Write metadata
            with self.fs_overlay.open(self.overlay_path + "/.meta", "w") as f:
                f.write("meta")  # Touch the file
            return True
        else:
            return exists

    def _delete_data(self) -> None:
        # Remove the voxel spacing folder
        if self.fs_overlay.exists(self.overlay_path):
            self.fs_overlay.rm(self.overlay_path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.overlay_path}")


class CopickRunFSSpec(CopickRunOverlay):
    """CopickRun class backed by fsspec storage.

    Attributes:
        static_path (str): The path to the run on the static source.
        overlay_path (str): The path to the run on the overlay source.
        fs_static (AbstractFileSystem): The filesystem containing the run on the static source.
        fs_overlay (AbstractFileSystem): The filesystem containing the run on the overlay source.
        static_is_overlay (bool): Whether the static and overlay sources are the same.
    """

    root: "CopickRootFSSpec"

    def _voxel_spacing_factory(self) -> Tuple[Type[CopickVoxelSpacingFSSpec], Type["CopickVoxelSpacingMeta"]]:
        return CopickVoxelSpacingFSSpec, CopickVoxelSpacingMeta

    def _picks_factory(self) -> Type[CopickPicksFSSpec]:
        return CopickPicksFSSpec

    def _mesh_factory(self) -> Tuple[Type[CopickMeshFSSpec], Type[CopickMeshMeta]]:
        return CopickMeshFSSpec, CopickMeshMeta

    def _segmentation_factory(self) -> Tuple[Type[CopickSegmentationFSSpec], Type[CopickSegmentationMeta]]:
        return CopickSegmentationFSSpec, CopickSegmentationMeta








    def _query_static_picks(self) -> List[CopickPicksFSSpec]:
        if self.static_is_overlay:
            return []

        pick_loc = f"{self.static_path}/Picks/"
        paths = self.fs_static.glob(pick_loc + "*.json")
        names = [n.replace(pick_loc, "").replace(".json", "") for n in paths]
        # Remove any hidden files?
        names = [n for n in names if not n.startswith(".")]

        users = [n.split("_")[0] for n in names]
        sessions = [n.split("_")[1] for n in names]
        objects = [n.split("_")[2] for n in names]

        assert len(users) == len(sessions) == len(objects)

        return [
            CopickPicksFSSpec(
                run=self,
                file=CopickPicksFile(
                    pickable_object_name=o,
                    user_id=u,
                    session_id=s,
                ),
                read_only=True,
            )
            for u, s, o in zip(users, sessions, objects, strict=True)
        ]

    def _query_overlay_picks(self) -> List[CopickPicksFSSpec]:
        pick_loc = f"{self.overlay_path}/Picks/"
        paths = self.fs_overlay.glob(pick_loc + "*.json")
        names = [n.replace(pick_loc, "").replace(".json", "") for n in paths]
        # Remove any hidden files?
        names = [n for n in names if not n.startswith(".")]

        users = [n.split("_")[0] for n in names]
        sessions = [n.split("_")[1] for n in names]
        objects = [n.split("_")[2] for n in names]

        assert len(users) == len(sessions) == len(objects)

        return [
            CopickPicksFSSpec(
                run=self,
                file=CopickPicksFile(
                    pickable_object_name=o,
                    user_id=u,
                    session_id=s,
                ),
                read_only=False,
            )
            for u, s, o in zip(users, sessions, objects, strict=True)
        ]





    def ensure(self, create: bool = False) -> bool:
        """Checks if the run record exists in the static or overlay directory, optionally creating it in the overlay
        filesystem if it does not.

        Args:
            create: Whether to create the run record if it does not exist.

        Returns:
            bool: True if the run record exists, False otherwise.
        """

        if self.static_is_overlay:
            exists = self.fs_overlay.exists(self.overlay_path)
        else:
            exists = self.fs_static.exists(self.static_path) or self.fs_overlay.exists(self.overlay_path)

        if not exists and create:
            self.fs_overlay.makedirs(self.overlay_path, exist_ok=True)
            # TODO: Write metadata
            with self.fs_overlay.open(self.overlay_path + "/.meta", "w") as f:
                f.write("meta")  # Touch the file
            return True
        else:
            return exists

    def _delete_data(self) -> None:
        # Remove the run folder
        if self.fs_overlay.exists(self.overlay_path):
            self.fs_overlay.rm(self.overlay_path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.overlay_path}")


class CopickObjectFSSpec(CopickObjectOverlay):
    """CopickObject class backed by fsspec storage.

    Attributes:
        static_path (str): The path to the object on the static source.
        overlay_path (str): The path to the object on the overlay source.
        fs_static (AbstractFileSystem): The filesystem for the static source.
        fs_overlay (AbstractFileSystem): The filesystem for the overlay source.
    """

    root: "CopickRootFSSpec"






    def zarr(self) -> Union[None, zarr.storage.FSStore]:
        """Get the zarr store for the object.

        Returns:
            Union[None, zarr.storage.FSStore]: The zarr store for the object, or None if the object is not a particle.
        """
        if not self.is_particle:
            return None

        if self.read_only:
            # For read-only access, use static filesystem and path
            fs = self.fs_static
            path = self.static_path
            mode = "r"
            create = False
        else:
            # For write access, always use overlay
            fs = self.fs_overlay
            path = self.overlay_path
            mode = "w"
            create = not fs.exists(path)

        return zarr.storage.FSStore(
            path,
            fs=fs,
            mode=mode,
            key_separator="/",
            dimension_separator="/",
            create=create,
        )


class CopickRootFSSpec(CopickRoot):
    """CopickRoot class backed by fspec storage.

    Attributes:
        fs_overlay (AbstractFileSystem): The filesystem for the overlay storage.
        fs_static (Optional[AbstractFileSystem]): The filesystem for the static storage.
        root_overlay (str): The root path for the overlay storage.
        root_static (Optional[str]): The root path for the static storage.
    """

    def __init__(self, config: CopickConfigFSSpec):
        """
        Args:
            config: Copick configuration for fsspec-based storage.
        """
        import weakref

        from copick.util.reconnecting_fs import ReconnectingFileSystem

        super().__init__(config)

        self.fs_overlay: AbstractFileSystem = ReconnectingFileSystem(
            config.overlay_root,
            config.overlay_fs_args,
        )
        self.fs_static: Optional[AbstractFileSystem] = None

        self.root_overlay: str = self.fs_overlay._strip_protocol(config.overlay_root).rstrip("/")
        self.root_static: Optional[str] = None

        if config.static_root is None:
            self.fs_static = self.fs_overlay
            self.root_static = self.fs_static._strip_protocol(config.overlay_root).rstrip("/")
        else:
            self.fs_static = ReconnectingFileSystem(config.static_root, config.static_fs_args)
            self.root_static = self.fs_static._strip_protocol(config.static_root).rstrip("/")

        # Set root reference for cache invalidation on reconnect
        self.fs_overlay._root_ref = weakref.ref(self)
        if self.fs_static is not self.fs_overlay:
            self.fs_static._root_ref = weakref.ref(self)


    def reconnect(self) -> None:
        """Force reconnection of all filesystems and invalidate caches."""
        pass

    @classmethod
    def from_file(cls, path: str) -> "CopickRootFSSpec":
        """Initialize a CopickRootFSSpec from a configuration file on disk.

        Args:
            path: Path to the configuration file on disk.

        Returns:
            CopickRootFSSpec: The initialized CopickRootFSSpec object.
        """
        with open(path, "r") as f:
            data = json.load(f)

        return cls(CopickConfigFSSpec(**data))

    def _run_factory(self) -> Tuple[Type[CopickRunFSSpec], Type["CopickRunMeta"]]:
        return CopickRunFSSpec, CopickRunMeta

    def _object_factory(self) -> Tuple[Type[CopickObjectFSSpec], Type[PickableObject]]:
        return CopickObjectFSSpec, PickableObject





    def _query_objects(self):
        """Override to check if each object from config exists in static or overlay filesystem."""
        pass
