"""Operations for managing copick objects (move, copy, delete)."""

from typing import Any, Dict, List, Optional, Union

from copick.models import CopickMesh, CopickPicks, CopickRoot, CopickRun, CopickSegmentation
from copick.util.log import get_logger
from copick.util.uri import parse_copick_uri, resolve_copick_objects, serialize_copick_uri

logger = get_logger(__name__)


def _validate_target_template(
    source_uri: str,
    target_uri: str,
    object_type: str,
    num_source_objects: int,
) -> None:
    """Validate that target URI is appropriate for the source pattern.

    Args:
        source_uri: Source URI pattern
        target_uri: Target URI (may contain templates)
        object_type: Type of object being moved/copied
        num_source_objects: Number of objects matched by source pattern

    Raises:
        ValueError: If target URI is invalid for the source pattern
    """
    pass


def _apply_template(
    template_uri: str,
    obj: Union[CopickPicks, CopickMesh, CopickSegmentation],
    object_type: str,
) -> str:
    """Apply template placeholders to generate a concrete URI.

    Args:
        template_uri: URI template with placeholders
        obj: Source copick object
        object_type: Type of object

    Returns:
        Concrete URI with placeholders replaced
    """
    result = template_uri

    # Replace placeholders based on object type
    if object_type in ("picks", "mesh"):
        result = result.replace("{object_name}", obj.pickable_object_name)
        result = result.replace("{user_id}", obj.user_id)
        result = result.replace("{session_id}", obj.session_id)
    elif object_type == "segmentation":
        result = result.replace("{name}", obj.name)
        result = result.replace("{user_id}", obj.user_id)
        result = result.replace("{session_id}", obj.session_id)
        result = result.replace("{voxel_spacing}", str(obj.voxel_size))

    return result


def remove_copick_objects(
    root: CopickRoot,
    object_type: str,
    uri: str,
    run_name: Optional[str] = None,
    dry_run: bool = False,
    log: bool = False,
) -> Dict[str, Any]:
    """Remove copick objects matching a URI pattern.

    Args:
        root: CopickRoot instance
        object_type: Type of object ('picks', 'mesh', 'segmentation', 'tomogram', 'feature')
        uri: Copick URI (supports patterns)
        run_name: Specific run name to operate on (None = all runs)
        dry_run: If True, only list objects that would be deleted
        log: Enable logging

    Returns:
        Dict with 'deleted' count and 'objects' list (URIs)

    Raises:
        ValueError: If object_type is invalid or URI is malformed
    """
    pass


def move_copick_objects(
    root: CopickRoot,
    object_type: str,
    source_uri: str,
    target_uri: str,
    run_name: Optional[str] = None,
    overwrite: bool = False,
    log: bool = False,
) -> Dict[str, Any]:
    """Move/rename copick objects by URI.

    For pattern-based operations, target_uri must contain template placeholders.
    For single object operations, target_uri should be concrete.

    Args:
        root: CopickRoot instance
        object_type: Type of object ('picks', 'mesh', 'segmentation')
        source_uri: Source copick URI (supports patterns)
        target_uri: Target copick URI (use templates for patterns)
        run_name: Specific run name to operate on (None = all runs)
        overwrite: Allow overwriting existing objects
        log: Enable logging

    Returns:
        Dict with 'moved' count, 'mappings' list of (source, target) tuples, and 'errors' list

    Raises:
        ValueError: If URIs are invalid or incompatible
    """
    pass


def copy_copick_objects(
    root: CopickRoot,
    object_type: str,
    source_uri: str,
    target_uri: str,
    run_name: Optional[str] = None,
    overwrite: bool = False,
    log: bool = False,
) -> Dict[str, Any]:
    """Copy/duplicate copick objects by URI.

    For pattern-based operations, target_uri must contain template placeholders.
    For single object operations, target_uri should be concrete.

    Args:
        root: CopickRoot instance
        object_type: Type of object ('picks', 'mesh', 'segmentation')
        source_uri: Source copick URI (supports patterns)
        target_uri: Target copick URI (use templates for patterns)
        run_name: Specific run name to operate on (None = all runs)
        overwrite: Allow overwriting existing objects
        log: Enable logging

    Returns:
        Dict with 'copied' count, 'mappings' list of (source, target) tuples, and 'errors' list

    Raises:
        ValueError: If URIs are invalid or incompatible
    """
    pass


# ============================================================================
# Per-run batch operations for parallelization
# ============================================================================


def remove_copick_objects_per_run(
    run: CopickRun,
    object_type: str,
    uri: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove copick objects matching a URI pattern within a single run.

    Worker function for parallel batch removal.

    Args:
        run: CopickRun instance to process
        object_type: Type of object ('picks', 'mesh', 'segmentation', 'tomogram', 'feature')
        uri: Copick URI (supports patterns)
        dry_run: If True, only list objects that would be deleted

    Returns:
        Dict with 'deleted' count, 'objects' list (URIs), and 'errors' list
    """
    try:
        # Resolve objects within this run only
        objects = resolve_copick_objects(uri, run.root, object_type, run.name)

        if not objects:
            return {"deleted": 0, "objects": [], "errors": []}

        deleted_uris = []
        errors = []

        if dry_run:
            for obj in objects:
                obj_uri = serialize_copick_uri(obj)
                deleted_uris.append(obj_uri)
        else:
            for obj in objects:
                obj_uri = serialize_copick_uri(obj)
                try:
                    obj.delete()
                    deleted_uris.append(obj_uri)
                except Exception as e:
                    errors.append(f"Failed to delete {obj_uri}: {e}")

        return {"deleted": len(deleted_uris), "objects": deleted_uris, "errors": errors}

    except Exception as e:
        logger.exception(f"Error in remove worker for run {run.name}: {e}")
        return {"deleted": 0, "objects": [], "errors": [f"Worker error in {run.name}: {e}"]}


def remove_copick_objects_batch(
    root: CopickRoot,
    object_type: str,
    uri: str,
    run_names: Optional[List[str]] = None,
    dry_run: bool = False,
    workers: int = 8,
) -> Dict[str, Any]:
    """Remove copick objects in parallel across multiple runs.

    Args:
        root: CopickRoot instance
        object_type: Type of object ('picks', 'mesh', 'segmentation', 'tomogram', 'feature')
        uri: Copick URI (supports patterns)
        run_names: List of run names to process (None = all runs)
        dry_run: If True, only list objects that would be deleted
        workers: Number of parallel workers

    Returns:
        Dict mapping run names to results
    """
    from copick.ops.run import map_runs

    runs_to_process = [run.name for run in root.runs] if run_names is None else run_names

    if not runs_to_process:
        return {}


    task_desc = "[DRY RUN] Removing objects" if dry_run else "Removing objects"
    results = map_runs(
        callback=run_worker,
        root=root,
        runs=runs_to_process,
        workers=workers,
        task_desc=task_desc,
    )

    return results


def move_copick_objects_per_run(
    run: CopickRun,
    object_type: str,
    source_uri: str,
    target_uri: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Move/rename copick objects by URI within a single run.

    Worker function for parallel batch moving.

    Args:
        run: CopickRun instance to process
        object_type: Type of object ('picks', 'mesh', 'segmentation')
        source_uri: Source copick URI (supports patterns)
        target_uri: Target copick URI (may contain templates)
        overwrite: Allow overwriting existing objects

    Returns:
        Dict with 'moved' count, 'mappings' list, and 'errors' list
    """
    try:
        if object_type not in ("picks", "mesh", "segmentation"):
            return {
                "moved": 0,
                "mappings": [],
                "errors": [f"Move operation not supported for object type: {object_type}"],
            }

        # Resolve source objects within this run only
        source_objects = resolve_copick_objects(source_uri, run.root, object_type, run.name)

        if not source_objects:
            return {"moved": 0, "mappings": [], "errors": []}

        mappings = []
        errors = []

        for source_obj in source_objects:
            source_obj_uri = serialize_copick_uri(source_obj)

            try:
                # Generate target URI (apply templates if present)
                concrete_target_uri = _apply_template(target_uri, source_obj, object_type)

                # Parse target to get new parameters
                target_params = parse_copick_uri(concrete_target_uri, object_type)

                # Create new object with target parameters
                if object_type == "picks":
                    target_obj = source_obj.run.new_picks(
                        object_name=target_params["object_name"],
                        session_id=target_params["session_id"],
                        user_id=target_params["user_id"],
                        exist_ok=overwrite,
                    )
                elif object_type == "mesh":
                    target_obj = source_obj.run.new_mesh(
                        object_name=target_params["object_name"],
                        session_id=target_params["session_id"],
                        user_id=target_params["user_id"],
                        exist_ok=overwrite,
                    )
                elif object_type == "segmentation":
                    voxel_spacing = target_params["voxel_spacing"]
                    if isinstance(voxel_spacing, str):
                        voxel_spacing = float(voxel_spacing)

                    target_obj = source_obj.run.new_segmentation(
                        name=target_params["name"],
                        session_id=target_params["session_id"],
                        user_id=target_params["user_id"],
                        voxel_size=voxel_spacing,
                        is_multilabel=source_obj.is_multilabel,
                        exist_ok=overwrite,
                    )

                # Copy data
                if object_type == "picks":
                    source_obj.load()
                    target_obj.points = source_obj.points
                    target_obj.store()
                elif object_type == "mesh":
                    source_obj.load()
                    target_obj.mesh = source_obj.mesh
                    target_obj.store()
                elif object_type == "segmentation":
                    data = source_obj.numpy()
                    target_obj.from_numpy(data)

                # Delete source object
                source_obj.delete()

                mappings.append((source_obj_uri, concrete_target_uri))

            except Exception as e:
                errors.append(f"Failed to move {source_obj_uri}: {e}")

        return {"moved": len(mappings), "mappings": mappings, "errors": errors}

    except Exception as e:
        logger.exception(f"Error in move worker for run {run.name}: {e}")
        return {"moved": 0, "mappings": [], "errors": [f"Worker error in {run.name}: {e}"]}


def move_copick_objects_batch(
    root: CopickRoot,
    object_type: str,
    source_uri: str,
    target_uri: str,
    run_names: Optional[List[str]] = None,
    overwrite: bool = False,
    workers: int = 8,
) -> Dict[str, Any]:
    """Move/rename copick objects in parallel across multiple runs.

    Args:
        root: CopickRoot instance
        object_type: Type of object ('picks', 'mesh', 'segmentation')
        source_uri: Source copick URI (supports patterns)
        target_uri: Target copick URI (may contain templates)
        run_names: List of run names to process (None = all runs)
        overwrite: Allow overwriting existing objects
        workers: Number of parallel workers

    Returns:
        Dict mapping run names to results
    """
    from copick.ops.run import map_runs

    runs_to_process = [run.name for run in root.runs] if run_names is None else run_names

    if not runs_to_process:
        return {}


    results = map_runs(
        callback=run_worker,
        root=root,
        runs=runs_to_process,
        workers=workers,
        task_desc="Moving objects",
    )

    return results


def copy_copick_objects_per_run(
    run: CopickRun,
    object_type: str,
    source_uri: str,
    target_uri: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Copy/duplicate copick objects by URI within a single run.

    Worker function for parallel batch copying.

    Args:
        run: CopickRun instance to process
        object_type: Type of object ('picks', 'mesh', 'segmentation')
        source_uri: Source copick URI (supports patterns)
        target_uri: Target copick URI (may contain templates)
        overwrite: Allow overwriting existing objects

    Returns:
        Dict with 'copied' count, 'mappings' list, and 'errors' list
    """
    try:
        if object_type not in ("picks", "mesh", "segmentation"):
            return {
                "copied": 0,
                "mappings": [],
                "errors": [f"Copy operation not supported for object type: {object_type}"],
            }

        # Resolve source objects within this run only
        source_objects = resolve_copick_objects(source_uri, run.root, object_type, run.name)

        if not source_objects:
            return {"copied": 0, "mappings": [], "errors": []}

        mappings = []
        errors = []

        for source_obj in source_objects:
            source_obj_uri = serialize_copick_uri(source_obj)

            try:
                # Generate target URI (apply templates if present)
                concrete_target_uri = _apply_template(target_uri, source_obj, object_type)

                # Parse target to get new parameters
                target_params = parse_copick_uri(concrete_target_uri, object_type)

                # Create new object with target parameters
                if object_type == "picks":
                    target_obj = source_obj.run.new_picks(
                        object_name=target_params["object_name"],
                        session_id=target_params["session_id"],
                        user_id=target_params["user_id"],
                        exist_ok=overwrite,
                    )
                elif object_type == "mesh":
                    target_obj = source_obj.run.new_mesh(
                        object_name=target_params["object_name"],
                        session_id=target_params["session_id"],
                        user_id=target_params["user_id"],
                        exist_ok=overwrite,
                    )
                elif object_type == "segmentation":
                    voxel_spacing = target_params["voxel_spacing"]
                    if isinstance(voxel_spacing, str):
                        voxel_spacing = float(voxel_spacing)

                    target_obj = source_obj.run.new_segmentation(
                        name=target_params["name"],
                        session_id=target_params["session_id"],
                        user_id=target_params["user_id"],
                        voxel_size=voxel_spacing,
                        is_multilabel=source_obj.is_multilabel,
                        exist_ok=overwrite,
                    )

                # Copy data (same as move, but without deleting source)
                if object_type == "picks":
                    source_obj.load()
                    target_obj.points = source_obj.points
                    target_obj.store()
                elif object_type == "mesh":
                    source_obj.load()
                    target_obj.mesh = source_obj.mesh
                    target_obj.store()
                elif object_type == "segmentation":
                    data = source_obj.numpy()
                    target_obj.from_numpy(data)

                mappings.append((source_obj_uri, concrete_target_uri))

            except Exception as e:
                errors.append(f"Failed to copy {source_obj_uri}: {e}")

        return {"copied": len(mappings), "mappings": mappings, "errors": errors}

    except Exception as e:
        logger.exception(f"Error in copy worker for run {run.name}: {e}")
        return {"copied": 0, "mappings": [], "errors": [f"Worker error in {run.name}: {e}"]}


def copy_copick_objects_batch(
    root: CopickRoot,
    object_type: str,
    source_uri: str,
    target_uri: str,
    run_names: Optional[List[str]] = None,
    overwrite: bool = False,
    workers: int = 8,
) -> Dict[str, Any]:
    """Copy/duplicate copick objects in parallel across multiple runs.

    Args:
        root: CopickRoot instance
        object_type: Type of object ('picks', 'mesh', 'segmentation')
        source_uri: Source copick URI (supports patterns)
        target_uri: Target copick URI (may contain templates)
        run_names: List of run names to process (None = all runs)
        overwrite: Allow overwriting existing objects
        workers: Number of parallel workers

    Returns:
        Dict mapping run names to results
    """
    from copick.ops.run import map_runs

    runs_to_process = [run.name for run in root.runs] if run_names is None else run_names

    if not runs_to_process:
        return {}


    results = map_runs(
        callback=run_worker,
        root=root,
        runs=runs_to_process,
        workers=workers,
        task_desc="Copying objects",
    )

    return results
