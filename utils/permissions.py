import discord
from discord import app_commands


def get_permissions_config(interaction: discord.Interaction) -> dict:
    bot = interaction.client
    config = getattr(bot, "config_data", {})
    return config.get("permissions", {})


def user_has_admin_role(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False

    permissions_config = get_permissions_config(interaction)

    allow_discord_administrator = bool(
        permissions_config.get("allow_discord_administrator", True)
    )

    if allow_discord_administrator and interaction.user.guild_permissions.administrator:
        return True

    admin_role_ids = permissions_config.get("admin_role_ids", [])

    if not admin_role_ids:
        return False

    allowed_role_ids = {int(role_id) for role_id in admin_role_ids}
    user_role_ids = {role.id for role in interaction.user.roles}

    return bool(allowed_role_ids.intersection(user_role_ids))


def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return user_has_admin_role(interaction)

    return app_commands.check(predicate)


async def handle_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> bool:
    if isinstance(error, app_commands.CheckFailure):
        permissions_config = get_permissions_config(interaction)

        deny_message = permissions_config.get(
            "deny_message",
            "⛔ Du hast keine Berechtigung für diesen Bot-Befehl.",
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                deny_message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                deny_message,
                ephemeral=True,
            )

        return True

    return False