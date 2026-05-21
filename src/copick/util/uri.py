import fnmatch
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qs

from copick.models import (
    CopickFeatures,
    CopickMesh,
    CopickPicks,
    CopickRoot,
    CopickRun,
    CopickSegmentation,
    CopickTomogram,
)

# ============================================================================
# URI Parsing
# ============================================================================


def parse_copick_uri(uri: str, object_type: str) -> Dict[str, Any]:
    """Parse a copick object URI according to the copick URI schemes.

    URI Schemes:
    - Picks: object_name:user_id/session_id
    - Meshes: object_name:user_id/session_id
    - Segmentations: name:user_id/session_id@voxel_spacing?multilabel=true
    - Tomogram: tomo_type@voxel_spacing
    - Feature: tomo_type@voxel_spacing:feature_type

    Pattern Support:
    - Glob patterns by default (e.g., 'mt*:user*/session*')
    - Use 're:' prefix for regex patterns (e.g., 're:mt.*:user_\\d+/session_\\d+')
    - Incomplete patterns match everything (e.g., 'mt:user' → 'mt:user/*')
    - Missing components become wildcards (e.g., 'mt' for picks → 'mt:*/*')

    Args:
        uri (str): The copick URI to parse.
        object_type (str): Type of object ('picks', 'mesh', 'segmentation', 'tomogram', 'feature').

    Returns:
        Dict[str, Any]: A dictionary containing the parsed components.
                       Includes 'pattern_type' field ('glob' or 'regex').

    Raises:
        ValueError: If the URI format is invalid or object_type is unknown.
    """
    # Remove any leading/trailing whitespace
    uri = uri.strip()

    # Check for regex prefix
    pattern_type = "glob"
    if uri.startswith("re:"):
        pattern_type = "regex"
        uri = uri[3:]  # Remove 're:' prefix

    # Handle query parameters (for segmentations)
    query_params = {}
    if "?" in uri:
        uri, query_string = uri.split("?", 1)
        query_params = parse_qs(query_string)
        # Flatten single-value lists
        query_params = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}

    if object_type in ("picks", "mesh"):
        # Pattern: object_name:user_id/session_id
        # Support incomplete patterns: 'obj' → 'obj:*/*', 'obj:user' → 'obj:user/*'
        parts = uri.split(":")
        if len(parts) == 1:
            # Just object_name
            object_name = parts[0]
            user_id = "*"
            session_id = "*"
        elif len(parts) == 2:
            object_name = parts[0]
            session_part = parts[1]
            if "/" in session_part:
                user_id, session_id = session_part.split("/", 1)
            else:
                user_id = session_part
                session_id = "*"
        else:
            raise ValueError(f"Invalid {object_type} URI format: '{uri}'")

        return {
            "object_type": object_type,
            "pattern_type": pattern_type,
            "object_name": object_name,
            "user_id": user_id,
            "session_id": session_id,
        }

    elif object_type == "segmentation":
        # Pattern: name:user_id/session_id@voxel_spacing
        # Support incomplete: 'name' → 'name:*/*@*', 'name:user' → 'name:user/*@*', etc.

        # Split by @ first to get voxel_spacing
        if "@" in uri:
            main_part, voxel_spacing = uri.split("@", 1)
        else:
            main_part = uri
            voxel_spacing = "*"

        # Now parse the main part
        parts = main_part.split(":")
        if len(parts) == 1:
            name = parts[0]
            user_id = "*"
            session_id = "*"
        elif len(parts) == 2:
            name = parts[0]
            session_part = parts[1]
            if "/" in session_part:
                user_id, session_id = session_part.split("/", 1)
            else:
                user_id = session_part
                session_id = "*"
        else:
            raise ValueError(f"Invalid segmentation URI format: '{uri}'")

        result = {
            "object_type": "segmentation",
            "pattern_type": pattern_type,
            "name": name,
            "user_id": user_id,
            "session_id": session_id,
            "voxel_spacing": voxel_spacing,
            "multilabel": None,  # Default value (matches both multilabel and non-multilabel)
        }

        # Check for multilabel parameter
        if "multilabel" in query_params:
            multilabel_val = query_params["multilabel"].lower()
            result["multilabel"] = multilabel_val in ("true", "1", "yes")

        return result

    elif object_type == "tomogram":
        # Pattern: tomo_type@voxel_spacing
        # Support incomplete: 'tomo' → 'tomo@*'
        if "@" in uri:
            tomo_type, voxel_spacing = uri.split("@", 1)
        else:
            tomo_type = uri
            voxel_spacing = "*"

        return {
            "object_type": "tomogram",
            "pattern_type": pattern_type,
            "tomo_type": tomo_type,
            "voxel_spacing": voxel_spacing,
        }

    elif object_type == "feature":
        # Pattern: tomo_type@voxel_spacing:feature_type
        # Support incomplete: 'tomo' → 'tomo@*:*', 'tomo@10' → 'tomo@10:*'

        # Split by @ first
        if "@" in uri:
            tomo_type, rest = uri.split("@", 1)
            # Now check if we have feature_type
            if ":" in rest:
                voxel_spacing, feature_type = rest.split(":", 1)
            else:
                voxel_spacing = rest
                feature_type = "*"
        else:
            tomo_type = uri
            voxel_spacing = "*"
            feature_type = "*"

        return {
            "object_type": "feature",
            "pattern_type": pattern_type,
            "tomo_type": tomo_type,
            "voxel_spacing": voxel_spacing,
            "feature_type": feature_type,
        }

    else:
        raise ValueError(
            f"Unknown object type: {object_type}. Must be one of: picks, mesh, segmentation, tomogram, feature",
        )


# ============================================================================
# URI Expansion (Smart Defaults)
# ============================================================================


def expand_output_uri(
    output_uri: str,
    input_uri: str,
    input_type: str,
    output_type: str,
    command_name: Optional[str] = None,
    individual_outputs: bool = False,
) -> str:
    """Expand a shorthand output URI with smart defaults from input URI and context.

    This function enables concise output specifications by inferring missing components
    from the input URI and command context. Full URIs pass through unchanged.

    Smart Default Rules:
        1. Object/Name: Use input's object_name/name if missing
        2. User ID: Use command_name if missing, or "converter" as fallback
        3. Session ID: Use placeholder templates based on context:
           - Pattern input → "{input_session_id}"
           - Individual outputs → "{instance_id}"
           - Exact input → "converted-001" (generic name)
        4. Voxel spacing (segmentation): Inherit from input if available
        5. Multilabel (segmentation): Inherit from input if available

    Supported Shorthand Formats:
        - "membrane" → "membrane:mesh2seg/converted-001@10.0" (name only)
        - "membrane:custom" → "membrane:custom/{input_session_id}" (name + user)
        - "membrane/my-session" → "membrane:mesh2seg/my-session@10.0" (name + session, default user)
        - "/my-session" → "membrane:mesh2seg/my-session@10.0" (session only, inherit name+user)
        - "{input_session_id}" → "membrane:mesh2seg/{input_session_id}@10.0" (placeholder)
        - "membrane:mesh2seg/my-session@10.0" → unchanged (full URI)

    Args:
        output_uri: Output URI (can be shorthand or full).
        input_uri: Input URI to inherit defaults from.
        input_type: Type of input object ('picks', 'mesh', 'segmentation').
        output_type: Type of output object ('picks', 'mesh', 'segmentation').
        command_name: Name of the command (used as default user_id).
        individual_outputs: Whether creating individual outputs (affects session_id template).

    Returns:
        str: Fully expanded output URI.

    Raises:
        ValueError: If URIs cannot be parsed or required information is missing.
    """
    # Parse input URI to extract defaults
    input_params = parse_copick_uri(input_uri, input_type)

    # Check if output_uri is already complete by trying to parse it
    # A complete URI will successfully parse with all required fields
    try:
        output_params = parse_copick_uri(output_uri, output_type)

        # Check if all required fields are present (not wildcards)
        has_object_name = output_params.get("object_name", "*") != "*" or output_params.get("name", "*") != "*"
        has_user_id = output_params.get("user_id", "*") != "*"
        has_session_id = output_params.get("session_id", "*") != "*"

        # For segmentations, check voxel_spacing too
        if output_type == "segmentation":
            has_voxel_spacing = output_params.get("voxel_spacing", "*") != "*"
            is_complete = has_object_name and has_user_id and has_session_id and has_voxel_spacing
        else:
            is_complete = has_object_name and has_user_id and has_session_id

        # If complete, return as-is
        if is_complete:
            return output_uri

    except (ValueError, KeyError):
        # Parsing failed or incomplete - proceed with expansion
        pass

    # Extract input components
    input_object_name = input_params.get("object_name") or input_params.get("name")
    input_user_id = input_params.get("user_id", "*")
    input_session_id = input_params.get("session_id", "*")
    input_voxel_spacing = input_params.get("voxel_spacing")
    input_multilabel = input_params.get("multilabel")

    # Determine if input uses patterns
    has_input_pattern = (
        "*" in str(input_object_name)
        or "*" in input_user_id
        or "*" in input_session_id
        or "?" in input_session_id
        or input_params.get("pattern_type") == "regex"
    )

    # Parse what we have in output_uri (might be partial)
    output_parts = {"object_name": None, "user_id": None, "session_id": None, "voxel_spacing": None, "multilabel": None}

    # Handle query parameters first (for segmentations)
    uri_to_parse = output_uri
    if "?" in uri_to_parse:
        uri_to_parse, query_string = uri_to_parse.split("?", 1)
        query_params = parse_qs(query_string)
        if "multilabel" in query_params:
            multilabel_val = query_params["multilabel"][0].lower()
            output_parts["multilabel"] = multilabel_val in ("true", "1", "yes")

    # Extract voxel_spacing if present (segmentation only)
    if output_type == "segmentation" and "@" in uri_to_parse:
        uri_to_parse, voxel_spacing_str = uri_to_parse.rsplit("@", 1)
        output_parts["voxel_spacing"] = voxel_spacing_str

    # Check if output_uri is just a placeholder
    if uri_to_parse.strip() in ("{input_session_id}", "{instance_id}"):
        output_parts["session_id"] = uri_to_parse.strip()
    else:
        # Parse the main part: object_name:user_id/session_id
        if ":" in uri_to_parse:
            # Standard format: name:user/session or name:user
            parts = uri_to_parse.split(":", 1)
            output_parts["object_name"] = parts[0]
            if "/" in parts[1]:
                output_parts["user_id"], output_parts["session_id"] = parts[1].split("/", 1)
            else:
                output_parts["user_id"] = parts[1]
        elif "/" in uri_to_parse:
            # Shorthand format: name/session or /session
            # This enables specifying session while using default user_id
            parts = uri_to_parse.split("/", 1)
            output_parts["object_name"] = parts[0] if parts[0] else None
            output_parts["session_id"] = parts[1]
            # user_id left as None → will use default from command_name
        else:
            # Just object_name
            output_parts["object_name"] = uri_to_parse

    # Apply defaults
    # 1. Object/Name
    if not output_parts["object_name"]:
        output_parts["object_name"] = input_object_name

    # 2. User ID
    if not output_parts["user_id"]:
        output_parts["user_id"] = command_name if command_name else "converter"

    # 3. Session ID
    if not output_parts["session_id"]:
        if individual_outputs:
            output_parts["session_id"] = "{instance_id}"
        elif has_input_pattern:
            output_parts["session_id"] = "{input_session_id}"
        else:
            output_parts["session_id"] = "converted-001"

    # 4. Voxel spacing (segmentation only)
    if output_type == "segmentation" and not output_parts["voxel_spacing"] and input_voxel_spacing:
        if isinstance(input_voxel_spacing, str) and input_voxel_spacing != "*":
            output_parts["voxel_spacing"] = input_voxel_spacing
        elif isinstance(input_voxel_spacing, (int, float)):
            output_parts["voxel_spacing"] = str(input_voxel_spacing)

    # 5. Multilabel (segmentation only)
    if output_type == "segmentation" and output_parts["multilabel"] is None and input_multilabel is not None:
        output_parts["multilabel"] = input_multilabel

    # Reconstruct the URI
    if output_type in ("picks", "mesh"):
        expanded = f"{output_parts['object_name']}:{output_parts['user_id']}/{output_parts['session_id']}"
    elif output_type == "segmentation":
        expanded = f"{output_parts['object_name']}:{output_parts['user_id']}/{output_parts['session_id']}"
        if output_parts["voxel_spacing"]:
            expanded += f"@{output_parts['voxel_spacing']}"
        if output_parts["multilabel"]:
            expanded += "?multilabel=true"
    else:
        raise ValueError(f"Unsupported output_type for expansion: {output_type}")

    return expanded


# ============================================================================
# URI Serialization
# ============================================================================


def serialize_copick_uri(
    obj: Union[CopickPicks, CopickMesh, CopickSegmentation, CopickTomogram, CopickFeatures],
) -> str:
    """Serialize a copick object to its URI representation.

    Args:
        obj: A copick object (CopickPicks, CopickMesh, CopickSegmentation, CopickTomogram, or CopickFeatures).

    Returns:
        str: The URI representation of the object.

    Raises:
        ValueError: If the object type is not recognized.
    """
    if isinstance(obj, (CopickPicks, CopickMesh)):
        return f"{obj.pickable_object_name}:{obj.user_id}/{obj.session_id}"

    elif isinstance(obj, CopickSegmentation):
        uri = f"{obj.name}:{obj.user_id}/{obj.session_id}@{obj.voxel_size}"
        if obj.is_multilabel:
            uri += "?multilabel=true"
        return uri

    elif isinstance(obj, CopickTomogram):
        return f"{obj.tomo_type}@{obj.voxel_spacing.voxel_size}"

    elif isinstance(obj, CopickFeatures):
        return f"{obj.tomo_type}@{obj.tomogram.voxel_spacing.voxel_size}:{obj.feature_type}"

    else:
        raise ValueError(f"Unknown copick object type: {type(obj).__name__}")


def serialize_copick_uri_from_dict(
    object_type: str,
    object_name: Optional[str] = None,
    name: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tomo_type: Optional[str] = None,
    voxel_spacing: Optional[float] = None,
    feature_type: Optional[str] = None,
    multilabel: Optional[bool] = None,
) -> str:
    """Serialize copick object parameters into a URI according to copick URI schemes.

    Args:
        object_type (str): Type of copick object ('picks', 'mesh', 'segmentation', 'tomogram', 'feature')
        object_name (str, optional): Object name for picks/meshes
        name (str, optional): Name for segmentations
        user_id (str, optional): User ID for picks/meshes/segmentations
        session_id (str, optional): Session ID for picks/meshes/segmentations
        tomo_type (str, optional): Tomogram type for tomograms/features
        voxel_spacing (float, optional): Voxel spacing for segmentations/tomograms/features
        feature_type (str, optional): Feature type for features
        multilabel (bool, optional): Whether segmentation is multilabel

    Returns:
        str: The serialized copick URI

    Raises:
        ValueError: If required parameters are missing for the given object type
    """
    if object_type == "picks":
        if not all([object_name, user_id, session_id]):
            raise ValueError("Picks require object_name, user_id, and session_id")
        return f"{object_name}:{user_id}/{session_id}"

    elif object_type == "mesh":
        if not all([object_name, user_id, session_id]):
            raise ValueError("Meshes require object_name, user_id, and session_id")
        return f"{object_name}:{user_id}/{session_id}"

    elif object_type == "segmentation":
        if not all([name, user_id, session_id, voxel_spacing is not None]):
            raise ValueError("Segmentations require name, user_id, session_id, and voxel_spacing")
        uri = f"{name}:{user_id}/{session_id}@{voxel_spacing}"
        if multilabel is True:
            uri += "?multilabel=true"
        return uri

    elif object_type == "tomogram":
        if not all([tomo_type, voxel_spacing is not None]):
            raise ValueError("Tomograms require tomo_type and voxel_spacing")
        return f"{tomo_type}@{voxel_spacing}"

    elif object_type == "feature":
        if not all([tomo_type, voxel_spacing is not None, feature_type]):
            raise ValueError("Features require tomo_type, voxel_spacing, and feature_type")
        return f"{tomo_type}@{voxel_spacing}:{feature_type}"

    else:
        raise ValueError(f"Unknown object type: {object_type}")


# ============================================================================
# Object Resolution (Public API)
# ============================================================================


def resolve_copick_objects(
    uri: str,
    root: "CopickRoot",
    object_type: str,
    run_name: Optional[str] = None,
) -> List[Union["CopickPicks", "CopickMesh", "CopickSegmentation", "CopickTomogram", "CopickFeatures"]]:
    """Resolve a copick URI to actual copick objects.

    This function parses a URI string and delegates to get_copick_objects_by_type()
    for the actual filtering logic.

    Args:
        uri (str): The copick URI to resolve.
        root (CopickRoot): The copick root to search in.
        object_type (str): Type of object ('picks', 'mesh', 'segmentation', 'tomogram', 'feature').
        run_name (str, optional): Specific run name to search in. If None, searches all runs.

    Returns:
        List: List of matching copick objects.

    Raises:
        ValueError: If the URI is invalid or object_type is invalid.
    """
    # Parse the URI to extract filter parameters
    parsed = parse_copick_uri(uri, object_type)

    # Remove object_type and pattern_type from parsed dict as they're not needed by get_copick_objects_by_type
    parsed.pop("object_type", None)

    # Delegate to get_copick_objects_by_type with the parsed filters
    return get_copick_objects_by_type(root, object_type, run_name, **parsed)


def get_copick_objects_by_type(
    root: "CopickRoot",
    object_type: str,
    run_name: Optional[str] = None,
    **filters,
) -> List[Union["CopickPicks", "CopickMesh", "CopickSegmentation", "CopickTomogram", "CopickFeatures"]]:
    """Get copick objects by type with optional filters.

    This is a convenience function that provides a more direct way to query objects
    without needing to construct URIs. Uses CopickRun's built-in get_* methods when
    possible for exact matches, falls back to pattern matching only when needed.

    Args:
        root (CopickRoot): The copick root to search in.
        object_type (str): The type of objects to retrieve ('picks', 'mesh', 'segmentation', 'tomogram', 'feature').
        run_name (str, optional): Specific run name to search in.
        **filters: Additional filters based on object type.
                  For picks/meshes: object_name, user_id, session_id
                  For segmentations: name, user_id, session_id, voxel_spacing, multilabel
                  For tomograms: tomo_type, voxel_spacing
                  For features: tomo_type, voxel_spacing, feature_type

    Returns:
        List: List of matching copick objects.

    Raises:
        ValueError: If the object_type is invalid or required filters are missing.
    """
    # Get runs to search
    runs_to_search = []
    if run_name:
        run = root.get_run(run_name)
        if run is None:
            raise ValueError(f"Run '{run_name}' not found")
        runs_to_search = [run]
    else:
        runs_to_search = root.runs

    # Dispatch to type-specific handler
    handlers = {
        "picks": _get_picks_from_runs,
        "mesh": _get_meshes_from_runs,
        "segmentation": _get_segmentations_from_runs,
        "tomogram": _get_tomograms_from_runs,
        "feature": _get_features_from_runs,
    }

    if object_type not in handlers:
        raise ValueError(
            f"Unknown object type: {object_type}. Must be one of: picks, mesh, segmentation, tomogram, feature",
        )

    return handlers[object_type](runs_to_search, filters)


# ============================================================================
# Pattern Matching Helpers (Private)
# ============================================================================


def _is_pattern(value: str, pattern_type: str) -> bool:
    """Check if a value is actually a pattern (not just a literal string).

    Args:
        value: The value to check.
        pattern_type: Either "glob" or "regex".

    Returns:
        bool: True if the value is a pattern that requires matching.
    """
    pass


def _matches_pattern(value: str, pattern: str, pattern_type: str) -> bool:
    """Check if a value matches a pattern based on pattern type."""
    # Wildcard matches everything
    if pattern == "*":
        return True

    if pattern_type == "glob":
        return fnmatch.fnmatch(value, pattern)
    elif pattern_type == "regex":
        try:
            return re.match(pattern, value) is not None
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
    else:
        raise ValueError(f"Unknown pattern type: {pattern_type}")


def _matches_numeric_pattern(value: Union[str, float], pattern: str, pattern_type: str) -> bool:
    """Check if a numeric value matches a pattern."""
    # Wildcard matches everything
    if pattern == "*":
        return True

    if pattern_type == "glob":
        # For exact numeric comparison, try to match as numbers
        try:
            return float(value) == float(pattern)
        except (ValueError, TypeError):
            # Fall back to string matching for non-numeric patterns
            return _matches_pattern(str(value), pattern, pattern_type)
    else:
        # For regex, convert value to string for matching
        return _matches_pattern(str(value), pattern, pattern_type)


# ============================================================================
# Type-Specific Object Handlers (Private)
# ============================================================================


def _get_picks_from_runs(
    runs: List["CopickRun"],
    filters: Dict[str, Any],
) -> List["CopickPicks"]:
    """Get picks using CopickRun.get_picks when possible for exact matches.

    Args:
        runs: List of runs to search.
        filters: Filter dictionary with optional keys: object_name, user_id, session_id, pattern_type.

    Returns:
        List of matching picks.
    """
    pass


def _get_meshes_from_runs(
    runs: List["CopickRun"],
    filters: Dict[str, Any],
) -> List["CopickMesh"]:
    """Get meshes using CopickRun.get_meshes when possible for exact matches.

    Args:
        runs: List of runs to search.
        filters: Filter dictionary with optional keys: object_name, user_id, session_id, pattern_type.

    Returns:
        List of matching meshes.
    """
    pass


def _get_segmentations_from_runs(
    runs: List["CopickRun"],
    filters: Dict[str, Any],
) -> List["CopickSegmentation"]:
    """Get segmentations using CopickRun.get_segmentations when possible for exact matches.

    Args:
        runs: List of runs to search.
        filters: Filter dictionary with optional keys: name, user_id, session_id, voxel_spacing, multilabel, pattern_type.

    Returns:
        List of matching segmentations.
    """
    pass


def _get_tomograms_from_runs(
    runs: List["CopickRun"],
    filters: Dict[str, Any],
) -> List["CopickTomogram"]:
    """Get tomograms with optional filtering.

    Args:
        runs: List of runs to search.
        filters: Filter dictionary with optional keys: tomo_type, voxel_spacing, pattern_type.

    Returns:
        List of matching tomograms.
    """
    pass


def _get_features_from_runs(
    runs: List["CopickRun"],
    filters: Dict[str, Any],
) -> List["CopickFeatures"]:
    """Get features with simplified nesting and use of built-in methods.

    Args:
        runs: List of runs to search.
        filters: Filter dictionary with optional keys: tomo_type, voxel_spacing, feature_type, pattern_type.

    Returns:
        List of matching features.
    """
    pass
