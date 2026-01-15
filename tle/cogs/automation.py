import discord
from discord.ext import commands, tasks
import logging
import datetime
import pytz
import json
from typing import Optional, List
from collections import defaultdict

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import db

logger = logging.getLogger(__name__)

class AutomationCogError(commands.CommandError):
    pass

class Automation(commands.Cog):
    """Automated standings, leaderboard posts, and rank monitoring"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.weekly_standings_task.start()
        self.monthly_standings_task.start()
        self.rank_monitor.start()

    def cog_unload(self):
        self.weekly_standings_task.cancel()
        self.monthly_standings_task.cancel()
        self.rank_monitor.cancel()

    def _get_setting(self, guild_id: int, setting_type: str):
        query = 'SELECT channel_id, role_name FROM automation_settings_v2 WHERE guild_id = ? AND setting_type = ?'
        return cf_common.user_db._fetchone(query, (str(guild_id), setting_type))

    def _set_setting(self, guild_id: int, setting_type: str, channel_id: int, role_name: str = None):
        query = '''
            INSERT OR REPLACE INTO automation_settings_v2 (guild_id, channel_id, setting_type, role_name)
            VALUES (?, ?, ?, ?)
        '''
        cf_common.user_db.conn.execute(query, (str(guild_id), str(channel_id), setting_type, role_name))
        cf_common.user_db.conn.commit()

    @commands.command(brief='Bind channel for weekly standings of a specific role')
    @commands.has_permissions(administrator=True)
    async def weekly_standings(self, ctx, role: discord.Role):
        """ربط القناة الحالية لعرض الترتيب الأسبوعي لرتبة معينة (كل جمعة الساعة 12:00 ظهراً)."""
        self._set_setting(ctx.guild.id, 'weekly', ctx.channel.id, role.name)
        embed = discord_common.embed_success(f"✅ تم ربط القناة برتبة **{role.name}** لعرض الترتيب الأسبوعي.")
        await ctx.send(embed=embed)

    @commands.command(brief='Set current channel as Master Event Channel')
    @commands.has_permissions(administrator=True)
    async def master_channel(self, ctx):
        """تعيين القناة الحالية كقناة الإعلانات الرئيسية للترتيب العالمي والترقيات."""
        self._set_setting(ctx.guild.id, 'master', ctx.channel.id)
        embed = discord_common.embed_success("🏆 تم تعيين القناة كـ **قناة الإعلانات الرئيسية**.")
        await ctx.send(embed=embed)

    @tasks.loop(time=datetime.time(hour=10, minute=0, tzinfo=pytz.UTC)) # Friday 12:00 PM Cairo
    async def weekly_standings_task(self):
        if datetime.datetime.now(pytz.UTC).weekday() != 4:
            return
        
        for guild in self.bot.guilds:
            setting = self._get_setting(guild.id, 'weekly')
            if not setting: continue
            
            channel = guild.get_channel(int(setting.channel_id))
            if not channel: continue
            
            role_name = setting.role_name
            users = cf_common.user_db.get_cf_users_for_guild(str(guild.id))
            
            filtered_users = []
            for user_id, user in users:
                member = guild.get_member(user_id)
                if member and any(r.name == role_name for r in member.roles):
                    filtered_users.append((user_id, user))
            
            filtered_users.sort(key=lambda x: x[1].rating or 0, reverse=True)
            
            embed = self._create_standings_embed(
                f"📊 الترتيب الأسبوعي - {role_name}",
                filtered_users[:10],
                guild
            )
            await channel.send(embed=embed)

    @tasks.loop(time=datetime.time(hour=10, minute=0, tzinfo=pytz.UTC)) # 1st of Month 12:00 PM Cairo
    async def monthly_standings_task(self):
        if datetime.datetime.now(pytz.UTC).day != 1:
            return
        
        for guild in self.bot.guilds:
            setting = self._get_setting(guild.id, 'master')
            if not setting: continue
            
            channel = guild.get_channel(int(setting.channel_id))
            if not channel: continue
            
            users = cf_common.user_db.get_cf_users_for_guild(str(guild.id))
            users.sort(key=lambda x: x[1].rating or 0, reverse=True)
            
            embed = self._create_standings_embed(
                f"🌍 الترتيب الشهري العالمي - {datetime.datetime.now().strftime('%B %Y')}",
                users[:20],
                guild
            )
            await channel.send(embed=embed)

    @tasks.loop(minutes=30)
    async def rank_monitor(self):
        """Monitor rating changes and update roles/notify master channel."""
        for guild in self.bot.guilds:
            master_setting = self._get_setting(guild.id, 'master')
            master_channel = guild.get_channel(int(master_setting.channel_id)) if master_setting else None
            
            users = cf_common.user_db.get_cf_users_for_guild(str(guild.id))
            for user_id, user in users:
                member = guild.get_member(user_id)
                if not member: continue
                
                new_rank = cf.rating2rank(user.rating).title
                current_rank_role = None
                cf_ranks = [r.title for r in cf.RANKS]
                for role in member.roles:
                    if role.name in cf_ranks:
                        current_rank_role = role.name
                        break
                
                if new_rank != current_rank_role:
                    try:
                        to_remove = [r for r in member.roles if r.name in cf_ranks and r.name != new_rank]
                        await member.remove_roles(*to_remove)
                        
                        new_role = discord.utils.get(guild.roles, name=new_rank)
                        if new_role:
                            await member.add_roles(new_role)
                        
                        if master_channel and user.rating:
                            embed = discord_common.embed_success(
                                f"🎉 **{member.display_name}** تم ترفيعه إلى رتبة **{new_rank}**!\\n"
                                f"التقييم الجديد: **{user.rating}**"
                            )
                            if member.avatar: embed.set_thumbnail(url=member.avatar.url)
                            await master_channel.send(embed=embed)
                            
                    except Exception as e:
                        self.logger.warning(f"Failed to update roles for {member.display_name}: {e}")

    def _create_standings_embed(self, title, users_data, guild):
        embed = discord.Embed(title=title, color=discord.Color.blue(), timestamp=datetime.datetime.utcnow())
        if not users_data:
            embed.description = "لا يوجد بيانات متاحة حالياً."
            return embed
        
        lines = []
        for i, (uid, user) in enumerate(users_data):
            member = guild.get_member(uid)
            name = member.display_name if member else user.handle
            emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            lines.append(f"{emoji} **{name}** - {user.rating or 0}")
        
        embed.description = "\n".join(lines)
        return embed

    @rank_monitor.before_loop
    @weekly_standings_task.before_loop
    @monthly_standings_task.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Automation(bot))
