import discord
from discord.ext import commands
import logging
from tle.util import discord_common

logger = logging.getLogger(__name__)

class AdminTools(commands.Cog):
    """ Administrative tools for server setup and role management """
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.command(brief="Initialize server roles (G1-G20, Admins)")
    @commands.has_permissions(administrator=True)
    @commands.command(brief="Initialize server roles (G1-G20, Admins)")
    @commands.has_permissions(administrator=True)
    async def init_roles(self, ctx):
        """
        Automatically initialize server roles:
        - Group roles: G1 to G20
        - Admin roles: Admin G1 to Admin G20
        - Master Role: ADMIN (Gold color)
        """
        status_msg = await ctx.send("Initializing roles... Please wait.")
        
        # 1. Master Admin Role (Gold)
        gold_color = discord.Color.from_rgb(255, 215, 0)
        master_admin_role = discord.utils.get(ctx.guild.roles, name="ADMIN")
        if not master_admin_role:
            try:
                master_admin_role = await ctx.guild.create_role(name="ADMIN", color=gold_color, reason="Setup gamified system", hoist=True)
                self.logger.info(f"Created role ADMIN in {ctx.guild.name}")
            except Exception as e:
                await ctx.send(f"Error creating ADMIN role: {e}")
        else:
            # Ensure color is Gold
            if master_admin_role.color != gold_color:
                await master_admin_role.edit(color=gold_color)

        # 2. Group Roles and Admin Group Roles
        created_count = 0
        for i in range(1, 21):
            group_name = f"G{i}"
            admin_group_name = f"Admin G{i}"
            
            # Create Group Role
            if not discord.utils.get(ctx.guild.roles, name=group_name):
                try:
                    await ctx.guild.create_role(name=group_name, reason="Setup gamified system groups")
                    created_count += 1
                except Exception as e:
                    self.logger.warning(f"Failed to create role {group_name}: {e}")

            # Create Admin Group Role
            if not discord.utils.get(ctx.guild.roles, name=admin_group_name):
                try:
                    await ctx.guild.create_role(name=admin_group_name, reason="Setup gamified system admin groups")
                    created_count += 1
                except Exception as e:
                    self.logger.warning(f"Failed to create role {admin_group_name}: {e}")

        embed = discord_common.embed_success(
            f"✅ Role initialization completed successfully!\n"
            f"- **ADMIN** role set to Gold.\n"
            f"- Roles **G1** to **G20** active.\n"
            f"- Admin roles **Admin G1** to **Admin G20** active."
        )
        await status_msg.edit(content=None, embed=embed)

async def setup(bot):
    await bot.add_cog(AdminTools(bot))
