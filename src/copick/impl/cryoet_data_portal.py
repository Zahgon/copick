import json
import random
import re
import time
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, Union

import cryoet_data_portal as cdp
import numpy as np
import s3fs
import zarr
from fsspec import AbstractFileSystem
from pydantic import BaseModel, create_model, field_validator

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
    CopickFeaturesMeta,
    CopickLocation,
    CopickMeshMeta,
    CopickPicksFile,
    CopickPoint,
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

# Exception class names from the gql transport layer that indicate transient server/network issues.
# Checked by class name through the MRO to avoid a hard dependency on the gql package
# (it is a transitive dependency of cryoet-data-portal).
_TRANSIENT_PORTAL_ERROR_NAMES = frozenset(
    {
        "TransportQueryError",
        "TransportError",
        "TransportServerError",
        "TransportClosed",
    },
)


def _is_transient_portal_error(exc: BaseException) -> bool:
    """Check if an exception indicates a transient data portal / GraphQL error."""
    return any(cls.__name__ in _TRANSIENT_PORTAL_ERROR_NAMES for cls in type(exc).__mro__)


def _retry_portal_call(fn, *args, max_retries=3, base_delay=1.0, max_delay=30.0, **kwargs):
    """Execute a data portal API call with retry on transient errors.

    Retries on network errors and GraphQL transport errors with exponential
    backoff + jitter. Non-transient exceptions (ValueError, TypeError, etc.)
    are raised immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError) as e:
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2**attempt) + random.uniform(0, 1), max_delay)
            logger.warning(
                "Portal API call %s failed (attempt %d/%d), retrying in %.1fs: %s",
                fn,
                attempt + 1,
                max_retries + 1,
                delay,
                e,
            )
            time.sleep(delay)
        except Exception as e:
            if _is_transient_portal_error(e) and attempt < max_retries:
                delay = min(base_delay * (2**attempt) + random.uniform(0, 1), max_delay)
                logger.warning(
                    "Portal API call %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    fn,
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    e,
                )
                time.sleep(delay)
            else:
                raise


def camel(s: str) -> str:
    s = re.sub(r"([_\-])+", " ", s).title().replace(" ", "")
    return "".join([s[0].lower(), s[1:]])


_portal_types = Union[Type[cdp.Annotation], Type[cdp.AnnotationFile], Type[cdp.Tomogram], Type[cdp.AnnotationShape]]


def _portal_to_model(clz: _portal_types, name: str) -> Type[BaseModel]:
    """Automatically create a Pydantic model from a CryoET Data Portal annotation class."""
    vals = clz.__annotations__
    scalars = {k: (Optional[v], None) for k, v in vals.items() if v in ["int", "float", "str", "bool"] and k[0] != "_"}
    return create_model(name, **scalars)


_PortalAnnotation = _portal_to_model(cdp.Annotation, "_PortalAnnotation")
_PortalAnnotationShape = _portal_to_model(cdp.AnnotationShape, "_PortalAnnotationShape")
_PortalAnnotationFile = _portal_to_model(cdp.AnnotationFile, "_PortalAnnotationFile")
_PortalTomogram = _portal_to_model(cdp.Tomogram, "_PortalTomogram")


@dataclass
class PortalCache:
    """Cache for portal annotation data shared across all runs."""

    picks_files_by_run: Dict[int, List[Any]] = field(default_factory=dict)  # Point/OrientedPoint
    seg_files_by_run: Dict[int, List[Any]] = field(default_factory=dict)  # SegmentationMask
    annotation_shapes: Dict[int, Any] = field(default_factory=dict)  # id -> shape
    annotations: Dict[int, Any] = field(default_factory=dict)  # id -> annotation
    author_names: Dict[int, List[str]] = field(default_factory=dict)  # annotation_id -> names
    voxel_spacings: Dict[int, Any] = field(default_factory=dict)  # id -> voxel_spacing

    # Tomogram cache
    tomograms_by_vs: Dict[int, List[Any]] = field(default_factory=dict)  # vs_id -> tomograms
    tomogram_authors: Dict[int, List[str]] = field(default_factory=dict)  # tomogram_id -> authors


class PortalAnnotationMeta(BaseModel):
    """A class to hold the portal anotation file information and the associated annotation file and shape."""

    portal_annotation: Optional[_PortalAnnotation] = _PortalAnnotation()
    portal_annotation_shape: Optional[_PortalAnnotationShape] = _PortalAnnotationShape()
    portal_annotation_file: Optional[_PortalAnnotationFile] = _PortalAnnotationFile()
    voxel_spacing: Optional[float] = None
    portal_author_names: Optional[List[str]] = []












    def compare(self, meta: Dict[str, Any], authors: List[str]) -> bool:
        # To convert to proper format
        qpm = _PortalAnnotation(**meta)
        qa = authors

        # Select fields to compare
        fields = list(qpm.model_fields_set)
        test_fields = [f for f in fields if getattr(qpm, f) is not None]

        # Check if all authors are in the list
        author_condition = all(a in self.portal_authors for a in qa)
        # Check if all fields are equal
        meta_condition = all(getattr(self.portal_annotation, f) == getattr(qpm, f) for f in test_fields)

        return author_condition and meta_condition


class PortalTomogramMeta(BaseModel):
    portal_metadata: Optional[_PortalTomogram] = _PortalTomogram()
    portal_authors: Optional[List[str]] = []

    @classmethod
    def from_portal_cached(cls, source: cdp.Tomogram, author_names: List[str]):
        """Create metadata from cached portal objects (avoids lazy loading for authors)."""
        pass

    def compare(self, meta: Dict[str, Any], authors: List[str]) -> bool:
        # To convert to proper format
        qpm = _PortalTomogram(**meta)
        qa = authors

        # Select fields to compare
        fields = list(qpm.model_fields_set)
        test_fields = [f for f in fields if getattr(qpm, f) is not None]

        # Check if all authors are in the list
        author_condition = all(a in self.portal_authors for a in qa)
        # Check if all fields are equal
        meta_condition = all(getattr(self.portal_metadata, f) == getattr(qpm, f) for f in test_fields)

        return author_condition and meta_condition


class CopickConfigCDP(CopickConfig):
    config_type: str = "cryoet_data_portal"
    overlay_root: str
    dataset_ids: List[int]

    overlay_fs_args: Optional[Dict[str, Any]] = {}


class CopickPicksFileCDP(CopickPicksFile):
    portal_metadata: Optional[PortalAnnotationMeta] = PortalAnnotationMeta()

    @classmethod
    def from_portal_container(cls, source: PortalAnnotationMeta, name: Optional[str] = None):
        """Create a CopickPicksFileCDP from portal metadata WITHOUT loading S3 data.

        Points are loaded lazily when accessed via the points property.
        """
        shape_type = source.shape_type
        user = "data-portal"
        session = str(source.annotation_file_id)
        object_name = f"{name}" if name else f"{camel(source.object_name)}-{source.annotation_file_id}"

        clz = cls(
            pickable_object_name=object_name,
            user_id=user,
            session_id=session,
            portal_metadata=source,
            points=[],  # Empty - will be loaded lazily
        )

        if shape_type == "OrientedPoint":
            clz.trust_orientation = True
        else:
            clz.trust_orientation = False

        return clz

    @staticmethod
    def _load_points_from_s3(portal_meta: PortalAnnotationMeta) -> List[CopickPoint]:
        """Load point data from S3 for a portal annotation.

        This is called lazily when points are first accessed.
        """
        fs = s3fs.S3FileSystem(anon=True)
        vs = portal_meta.voxel_spacing
        shape_type = portal_meta.shape_type
        points = []

        with fs.open(portal_meta.s3_path, "r") as f:
            content = f.read()

        for line in content.strip().split("\n"):
            data = json.loads(line)
            x = data["location"]["x"] * vs
            y = data["location"]["y"] * vs
            z = data["location"]["z"] * vs

            if shape_type == "OrientedPoint":
                mat = np.eye(4, 4)
                mat[:3, :3] = np.array(data["xyz_rotation_matrix"])
                point = CopickPoint(
                    location=CopickLocation(x=x, y=y, z=z),
                    transformation_=mat.tolist(),
                )
            else:
                point = CopickPoint(location=CopickLocation(x=x, y=y, z=z))
            points.append(point)

        return points





class CopickPicksCDP(CopickPicksOverlay):
    run: "CopickRunCDP"
    meta: CopickPicksFileCDP






    def _load(self) -> CopickPicksFile:
        # For read-only portal picks, load points from S3
        if self.read_only and self.meta.portal_metadata is not None:
            points = CopickPicksFileCDP._load_points_from_s3(self.meta.portal_metadata)
            # Update the metadata with loaded points
            return CopickPicksFileCDP(
                pickable_object_name=self.meta.pickable_object_name,
                user_id=self.meta.user_id,
                session_id=self.meta.session_id,
                portal_metadata=self.meta.portal_metadata,
                trust_orientation=self.meta.trust_orientation,
                points=points,
            )

        # For overlay picks, load from filesystem
        if not self.fs.exists(self.path):
            logger.critical(f"File not found: {self.path}")
            raise FileNotFoundError(f"File not found: {self.path}")

        with self.fs.open(self.path, "r") as f:
            data = json.load(f)

        return CopickPicksFileCDP(**data)

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


class CopickMeshCDP(CopickMeshOverlay):
    run: "CopickRunCDP"






    def _load(self) -> Union["Geometry", None]:
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

    def _delete_data(self):
        if self.fs.exists(self.path):
            self.fs.rm(self.path)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickSegmentationMetaCDP(CopickSegmentationMeta):
    portal_metadata: Optional[PortalAnnotationMeta] = PortalAnnotationMeta()





class CopickSegmentationCDP(CopickSegmentationOverlay):
    run: "CopickRunCDP"
    meta: CopickSegmentationMetaCDP







    def zarr(self) -> zarr.storage.FSStore:
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
        if self.fs.exists(self.path):
            self.fs.rm(self.path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickFeaturesCDP(CopickFeaturesOverlay):
    tomogram: "CopickTomogramCDP"



    def zarr(self) -> zarr.storage.FSStore:
        if self.read_only:
            logger.critical("Data portal does not support features (yet).")
            raise NotImplementedError("Data portal does not support features (yet).")
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
        if self.fs.exists(self.path):
            self.fs.rm(self.path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickTomogramMetaCDP(CopickTomogramMeta):
    portal_tomo_id: Optional[int] = None
    portal_tomo_path: Optional[str] = None
    portal_metadata: Optional[PortalTomogramMeta] = PortalTomogramMeta()



class CopickTomogramCDP(CopickTomogramOverlay):
    voxel_spacing: "CopickVoxelSpacingCDP"
    meta: CopickTomogramMetaCDP

    def _feature_factory(self) -> Tuple[Type[CopickFeaturesCDP], Type["CopickFeaturesMeta"]]:
        return CopickFeaturesCDP, CopickFeaturesMeta

    @property
    def tomo_type(self) -> str:
        """The type of tomogram. For data portal tomograms, this is derived as
        `cryoet_data_portal.Tomogram.reconstruction_method + "-" + cryoet_data_portal.Tomogram.processing + ["-" +
        cryoet_data_portal.Tomogram.processing_software + "-" + cryoet_data_portal.Tomogram.ctf_corrected`], where
        `cryoet_data_portal.Tomogram.processing_software` and `cryoet_data_portal.Tomogram.ctf_corrected` are discarded
        if null in the database.
        """
        pass

    @property
    def portal_tomo(self) -> bool:
        """Whether this tomogram is from the portal or not."""
        pass








    def zarr(self) -> zarr.storage.FSStore:
        if self.read_only:
            fs = s3fs.S3FileSystem(anon=True)
            path = self.meta.portal_tomo_path
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
        if self.fs_overlay.exists(self.overlay_path):
            self.fs_overlay.rm(self.overlay_path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.overlay_path}")


class CopickVoxelSpacingMetaCDP(CopickVoxelSpacingMeta):
    portal_vs_id: Optional[int] = None



class CopickVoxelSpacingCDP(CopickVoxelSpacingOverlay):
    run: "CopickRunCDP"
    meta: CopickVoxelSpacingMetaCDP

    def _tomogram_factory(self) -> Tuple[Type[CopickTomogramCDP], Type[CopickTomogramMetaCDP]]:
        return CopickTomogramCDP, CopickTomogramMetaCDP






    def ensure(self, create: bool = False) -> bool:
        """Checks if the voxel spacing record exists in the static or overlay directory, optionally creating it in the
        overlay filesystem if it does not.

        Args:
            create: Whether to create the voxel spacing record if it does not exist.

        Returns:
            bool: True if the voxel spacing record exists, False otherwise.
        """
        client = cdp.Client()
        vs = _retry_portal_call(
            cdp.TomogramVoxelSpacing.find,
            client,
            [  # noqa
                cdp.TomogramVoxelSpacing.run.id == self.run.portal_run_id,
                cdp.TomogramVoxelSpacing.voxel_spacing == self.meta.voxel_size,
            ],
        )
        exists = len(vs) > 0 or self.fs_overlay.exists(self.overlay_path)

        if len(vs) > 0:
            self.meta.portal_vs_id = vs[0].id

        if not exists and create:
            self.fs_overlay.makedirs(self.overlay_path, exist_ok=True)
            # TODO: Write metadata
            with self.fs_overlay.open(self.overlay_path + "/.meta", "w") as f:
                f.write("meta")  # Touch the file
            return True
        else:
            return exists

    def get_tomograms(
        self,
        tomo_type: str = None,
        portal_meta_query: Dict[str, Any] = None,
        portal_author_query: List[str] = None,
        **kwargs,
    ) -> List["CopickTomogramCDP"]:
        """Get a tomogram by type. Portal metadata are compared for equality. Authors are compared for inclusion.

        Args:
            tomo_type: The type of tomogram to get. For portal tomograms, this is
                `cryoet_data_portal.Tomogram.reconstruction_method.`
            portal_meta_query: Dictionary of values to compare against portal metadata of this tomogram. Allowed keys
                are the scalar fields of [cryoet_data_portal.Tomogram](https://chanzuckerberg.github.io/cryoet-data-portal/api_reference.html#cryoet_data_portal.Tomogram)
            portal_author_query: List of author names. Tomograms are included if this author is in the portal
                annotation's author list.
            **kwargs: Additional parameters passed to parent class.

        Returns:
            List[CopickTomogram]: The list of tomograms that match the query.
        """
        tomos = super().get_tomograms(tomo_type, **kwargs)

        if portal_meta_query is None:
            portal_meta_query = {}
        if portal_author_query is None:
            portal_author_query = []

        # Compare portal metadata and authors
        return [t for t in tomos if t.meta.portal_metadata.compare(portal_meta_query, portal_author_query)]

    def _delete_data(self) -> None:
        if self.fs_overlay.exists(self.overlay_path):
            self.fs_overlay.rm(self.overlay_path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.overlay_path}")


class CopickRunMetaCDP(CopickRunMeta):
    portal_run_id: Optional[int] = None
    portal_run_name: Optional[str] = None
    portal_dataset_id: Optional[int] = None



class CopickRunCDP(CopickRunOverlay):
    root: "CopickRootCDP"
    meta: CopickRunMetaCDP

    def _voxel_spacing_factory(self) -> Tuple[Type[CopickVoxelSpacingCDP], Type[CopickVoxelSpacingMetaCDP]]:
        return CopickVoxelSpacingCDP, CopickVoxelSpacingMetaCDP

    def _picks_factory(self) -> Type[CopickPicksCDP]:
        return CopickPicksCDP

    def _mesh_factory(self) -> Tuple[Type[CopickMeshCDP], Type[CopickMeshMeta]]:
        return CopickMeshCDP, CopickMeshMeta

    def _segmentation_factory(self) -> Tuple[Type[CopickSegmentationCDP], Type[CopickSegmentationMetaCDP]]:
        return CopickSegmentationCDP, CopickSegmentationMetaCDP








    def _query_static_picks(self) -> List[CopickPicksCDP]:
        # Run only added on overlay
        if self.portal_run_id is None:
            return []

        # Get cached data from root (fetches once for all runs)
        cache = self.root._ensure_annotation_cache()
        go_map = self.root.go_map

        # Filter annotation files for this run from cache
        point_anno_files = cache.picks_files_by_run.get(self.portal_run_id, [])
        if not point_anno_files:
            return []

        # Create picks using cached lookups
        portal_meta = [
            PortalAnnotationMeta(
                portal_annotation_file=af,
                portal_annotation_shape=cache.annotation_shapes[af.annotation_shape_id],
                portal_annotation=cache.annotations[cache.annotation_shapes[af.annotation_shape_id].annotation_id],
                voxel_spacing=cache.voxel_spacings[af.tomogram_voxel_spacing_id].voxel_spacing,
                portal_author_names=cache.author_names.get(
                    cache.annotation_shapes[af.annotation_shape_id].annotation_id,
                    [],
                ),
            )
            for af in point_anno_files
        ]

        return [
            CopickPicksCDP(
                run=self,
                file=CopickPicksFileCDP.from_portal_container(pm, name=go_map[pm.object_id]),
                read_only=True,
            )
            for pm in portal_meta
        ]

    def _query_overlay_picks(self) -> List[CopickPicksCDP]:
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
            CopickPicksCDP(
                run=self,
                file=CopickPicksFileCDP(
                    pickable_object_name=o,
                    user_id=u,
                    session_id=s,
                ),
                read_only=False,
            )
            for u, s, o in zip(users, sessions, objects, strict=True)
        ]

    def get_picks(
        self,
        object_name: str = None,
        user_id: str = None,
        session_id: str = None,
        portal_meta_query: Dict[str, Any] = None,
        portal_author_query: List[str] = None,
        **kwargs,
    ) -> List["CopickPicksCDP"]:
        """Get picks by name, user_id or session_id (or combinations). Portal metadata are compared for equality. Portal
        authors are checked for inclusion in the full author list.

        Args:
            object_name: Name of the object to search for.
            user_id: User ID to search for.
            session_id: Session ID to search for.
            portal_meta_query: Dictionary of values to compare against portal metadata of this annotation. Allowed keys
                are the scalar fields of [cryoet_data_portal.Annotation](https://chanzuckerberg.github.io/cryoet-data-portal/api_reference.html#cryoet_data_portal.Annotation)
            portal_author_query: List of author names. Segmentations are included if this author is in the portal
                annotation's author list.
            **kwargs: Additional parameters passed to parent class.

        Returns:
            List[CopickPicks]: List of picks that match the search criteria.
        """
        picks = super().get_picks(object_name, user_id, session_id, **kwargs)

        # Just return the regular output if no additional conditions
        if portal_meta_query is None and portal_author_query is None:
            return picks

        if portal_meta_query is None:
            portal_meta_query = {}

        if portal_author_query is None:
            portal_author_query = []

        # Compare the metadata
        picks = [p for p in picks if p.meta.portal_metadata.compare(portal_meta_query, portal_author_query)]

        return picks





    def get_segmentations(
        self,
        user_id: str = None,
        session_id: str = None,
        is_multilabel: bool = None,
        name: str = None,
        voxel_size: float = None,
        portal_meta_query: Dict[str, Any] = None,
        portal_author_query: List[str] = None,
        **kwargs,
    ) -> List["CopickSegmentationCDP"]:
        """Get segmentations by user_id, session_id, name, type or voxel_size (or combinations) and portal metadata and
        authors. Portal metadata are compared for equality. Portal authors are checked for inclusion in the full author
        list.

        Args:
            user_id: User ID to search for.
            session_id: Session ID to search for.
            is_multilabel: Whether the segmentation is multilabel or not.
            name: Name of the segmentation to search for.
            voxel_size: Voxel size to search for.
            portal_meta_query: Dictionary of values to compare against portal metadata of this annotation. Allowed keys
                are the scalar fields of [cryoet_data_portal.Annotation](https://chanzuckerberg.github.io/cryoet-data-portal/python-api.html#annotation)
            portal_author_query: List of author names. Segmentations are included if this author is in the portal
                annotation's author list.
            **kwargs: Additional parameters passed to parent class.

        Returns:
            List[CopickSegmentation]: List of segmentations that match the search criteria.
        """
        segmentations = super().get_segmentations(user_id, session_id, is_multilabel, name, voxel_size, **kwargs)

        # Just return the regular output if no additional conditions
        if portal_meta_query is None and portal_author_query is None:
            return segmentations

        if portal_meta_query is None:
            portal_meta_query = {}

        if portal_author_query is None:
            portal_author_query = []

        # Compare the metadata
        segmentations = [
            s
            for s in segmentations
            if s.meta.portal_metadata.compare(
                portal_meta_query,
                portal_author_query,
            )
        ]

        return segmentations

    def ensure(self, create: bool = False) -> bool:
        """Checks if the run record exists in the static or overlay directory, optionally creating it in the overlay
        filesystem if it does not.

        Args:
            create: Whether to create the run record if it does not exist.

        Returns:
            bool: True if the run record exists, False otherwise.
        """
        client = cdp.Client()
        try:
            id_from_name = int(self.name)
            run = _retry_portal_call(cdp.Run.get_by_id, client, id_from_name)
        except ValueError:
            run = None

        exists = run is not None or self.fs_overlay.exists(self.overlay_path)

        if run:
            self.meta.portal_run_id = run.id

        if not exists and create:
            self.fs_overlay.makedirs(self.overlay_path, exist_ok=True)
            # TODO: Write metadata
            with self.fs_overlay.open(self.overlay_path + "/.meta", "w") as f:
                f.write("meta")  # Touch the file
            return True
        else:
            return exists

    def _delete_data(self) -> None:
        if self.fs_overlay.exists(self.overlay_path):
            self.fs_overlay.rm(self.overlay_path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.overlay_path}")


class CopickObjectCDP(CopickObjectOverlay):
    root: "CopickRootCDP"



    def zarr(self) -> Union[None, zarr.storage.FSStore]:
        if not self.is_particle:
            return None

        # Return none if there is no density map
        if not self.fs.exists(self.path):
            return None

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
        if self.fs.exists(self.path):
            self.fs.rm(self.path, recursive=True)
        else:
            raise FileNotFoundError(f"File not found: {self.path}")


class CopickRootCDP(CopickRoot):
    config: CopickConfigCDP

    def __init__(self, config: CopickConfigCDP):
        import weakref

        from copick.util.reconnecting_fs import ReconnectingFileSystem

        super().__init__(config)

        self.fs_overlay: AbstractFileSystem = ReconnectingFileSystem(
            config.overlay_root,
            config.overlay_fs_args,
        )
        self.root_overlay: str = self.fs_overlay._strip_protocol(config.overlay_root)  # noqa
        self._portal_cache: Optional[PortalCache] = None

        # Set root reference for cache invalidation on reconnect
        self.fs_overlay._root_ref = weakref.ref(self)

        # Eagerly build annotation cache for all datasets
        self._ensure_annotation_cache()

    def reconnect(self) -> None:
        """Force reconnection of the overlay filesystem and invalidate caches."""
        pass


    def _ensure_annotation_cache(self) -> PortalCache:
        """Lazily fetch and cache all portal annotation data for picks, segmentations, and tomograms."""
        if self._portal_cache is not None:
            return self._portal_cache

        client = cdp.Client()
        go_map = self.go_map

        # 1. Fetch ALL annotation files for all datasets (picks + segmentations)
        all_anno_files = _retry_portal_call(
            cdp.AnnotationFile.find,
            client,
            [
                cdp.AnnotationFile.annotation_shape.annotation.run.dataset_id._in(self.dataset_ids),  # noqa
                cdp.AnnotationFile.annotation_shape.shape_type._in(
                    ["Point", "OrientedPoint", "SegmentationMask"],
                ),  # noqa
                cdp.AnnotationFile.annotation_shape.annotation.object_id._in(list(go_map.keys())),  # noqa
            ],
        )

        # 2. Fetch ALL annotation shapes (direct filters to avoid huge _in() lists)
        all_shapes = _retry_portal_call(
            cdp.AnnotationShape.find,
            client,
            [
                cdp.AnnotationShape.annotation.run.dataset_id._in(self.dataset_ids),  # noqa
                cdp.AnnotationShape.shape_type._in(["Point", "OrientedPoint", "SegmentationMask"]),  # noqa
                cdp.AnnotationShape.annotation.object_id._in(list(go_map.keys())),  # noqa
            ],
        )

        # 3. Fetch ALL annotations
        all_annotations = _retry_portal_call(
            cdp.Annotation.find,
            client,
            [
                cdp.Annotation.run.dataset_id._in(self.dataset_ids),  # noqa
                cdp.Annotation.object_id._in(list(go_map.keys())),  # noqa
            ],
        )

        # 4. Fetch ALL annotation authors
        all_authors = _retry_portal_call(
            cdp.AnnotationAuthor.find,
            client,
            [
                cdp.AnnotationAuthor.annotation.run.dataset_id._in(self.dataset_ids),  # noqa
                cdp.AnnotationAuthor.annotation.object_id._in(list(go_map.keys())),  # noqa
            ],
        )

        # 5. Fetch ALL voxel spacings
        all_voxel_spacings = _retry_portal_call(
            cdp.TomogramVoxelSpacing.find,
            client,
            [
                cdp.TomogramVoxelSpacing.run.dataset_id._in(self.dataset_ids),  # noqa
            ],
        )

        # 6. Fetch ALL tomograms for all datasets
        all_tomograms = _retry_portal_call(
            cdp.Tomogram.find,
            client,
            [
                cdp.Tomogram.tomogram_voxel_spacing.run.dataset_id._in(self.dataset_ids),  # noqa
            ],
        )

        # 7. Fetch ALL tomogram authors
        all_tomogram_authors = _retry_portal_call(
            cdp.TomogramAuthor.find,
            client,
            [
                cdp.TomogramAuthor.tomogram.tomogram_voxel_spacing.run.dataset_id._in(self.dataset_ids),  # noqa
            ],
        )

        # Build cache
        cache = PortalCache()

        # Index by id
        cache.annotation_shapes = {s.id: s for s in all_shapes}
        cache.annotations = {a.id: a for a in all_annotations}
        cache.voxel_spacings = {vs.id: vs for vs in all_voxel_spacings}

        # Group annotation files by run_id and shape_type
        for af in all_anno_files:
            shape = cache.annotation_shapes[af.annotation_shape_id]
            annotation = cache.annotations[shape.annotation_id]
            run_id = annotation.run_id

            if shape.shape_type in ["Point", "OrientedPoint"]:
                if run_id not in cache.picks_files_by_run:
                    cache.picks_files_by_run[run_id] = []
                cache.picks_files_by_run[run_id].append(af)
            elif shape.shape_type == "SegmentationMask" and af.format == "zarr":
                if run_id not in cache.seg_files_by_run:
                    cache.seg_files_by_run[run_id] = []
                cache.seg_files_by_run[run_id].append(af)

        # Build annotation author names lookup
        for author in all_authors:
            if author.annotation_id not in cache.author_names:
                cache.author_names[author.annotation_id] = []
            cache.author_names[author.annotation_id].append(author.name)

        # Group tomograms by voxel spacing
        for tomo in all_tomograms:
            vs_id = tomo.tomogram_voxel_spacing_id
            if vs_id not in cache.tomograms_by_vs:
                cache.tomograms_by_vs[vs_id] = []
            cache.tomograms_by_vs[vs_id].append(tomo)

        # Build tomogram author lookup
        for author in all_tomogram_authors:
            if author.tomogram_id not in cache.tomogram_authors:
                cache.tomogram_authors[author.tomogram_id] = []
            cache.tomogram_authors[author.tomogram_id].append(author.name)

        self._portal_cache = cache
        return cache



    @classmethod
    def from_file(cls, path: str) -> "CopickRootCDP":
        with open(path, "r") as f:
            data = json.load(f)

        return cls(CopickConfigCDP(**data))

    def _run_factory(self) -> Tuple[Type[CopickRunCDP], Type[CopickRunMetaCDP]]:
        return CopickRunCDP, CopickRunMetaCDP

    def _object_factory(self) -> Tuple[Type[CopickObjectCDP], Type[PickableObject]]:
        return CopickObjectCDP, PickableObject


    def _query_objects(self):
        """Override to create objects from config. For CryoET Data Portal, objects are always writable since they only exist in overlay."""
        pass
