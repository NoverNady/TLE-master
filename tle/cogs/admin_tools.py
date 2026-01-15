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
    async def init_roles(self, ctx):
        """
        تهيئة الأدوار الخاصة بالسيرفر تلقائياً:
        - أدوار المجموعات: G1 إلى G20
        - أدوار المشرفين: Admin G1 إلى Admin G20
        - الدور الرئيسي: ADMIN (باللون الذهبي المميز)
        """
        status_msg = await ctx.send("جاري تهيئة الرتب... يرجى الانتظار.")
        
        # 1. Master Admin Role (Gold)
        gold_color = discord.Color.from_rgb(255, 215, 0)
        master_admin_role = discord.utils.get(ctx.guild.roles, name="ADMIN")
        if not master_admin_role:
            try:
                master_admin_role = await ctx.guild.create_role(name="ADMIN", color=gold_color, reason="Setup gamified system", hoist=True)
                self.logger.info(f"Created role ADMIN in {ctx.guild.name}")
            except Exception as e:
                await ctx.send(f"خطأ أثناء إنشاء رتبة ADMIN: {e}")
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
            f"✅ تم الانتهاء من تهيئة الرتب بنجاح!\\n"
            f"- تم تفعيل رتبة **ADMIN** باللون الذهبي.\\n"
            f"- تم تفعيل الرتب من **G1** إلى **G20**.\\n"
            f"- تم تفعيل رتب المشرفين من **Admin G1** إلى **Admin G20**."
        )
        await status_msg.edit(content=None, embed=embed)

async def setup(bot):
    await bot.add_cog(AdminTools(bot))
