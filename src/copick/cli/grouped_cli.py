"""Custom Click Group for organizing commands into categories."""

from typing import Dict, List, Optional

import click


class GroupedCommandGroup(click.Group):
    """Custom Click Group that organizes commands into categories.

    Commands are displayed in categorized sections with headers in the help output.
    Each category displays its commands in alphabetical order.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the grouped command group.

        The command_categories attribute should be a dict mapping category names
        to lists of command names in that category.
        """
        self.command_categories: Dict[str, List[str]] = kwargs.pop("command_categories", {})
        super().__init__(*args, **kwargs)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format commands into categorized sections.

        This overrides the default Click behavior to group commands by category
        with section headers.
        """
        pass

    def _format_command_list(self, formatter: click.HelpFormatter, commands: List[tuple]) -> None:
        """Format a list of commands for display.

        Args:
            formatter: Click formatter to write to
            commands: List of (name, command) tuples
        """
        pass


def create_grouped_cli(
    name: Optional[str] = None,
    command_categories: Optional[Dict[str, List[str]]] = None,
    **kwargs,
) -> GroupedCommandGroup:
    """Create a GroupedCommandGroup with the specified categories.

    Args:
        name: Name of the CLI group
        command_categories: Dict mapping category names to lists of command names
        **kwargs: Additional arguments passed to GroupedCommandGroup

    Returns:
        GroupedCommandGroup instance
    """
    pass
