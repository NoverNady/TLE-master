import discord
from discord.ext import commands, tasks
import logging
import datetime
import pytz
import asyncio
from typing import List, Optional

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import db

logger = logging.getLogger(__name__)

class ScoringCogError(commands.CommandError):
    pass

class Scoring(commands.Cog):
    """Custom Scoring Engine for Gamified Community System"""
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.check_submissions.start()
        self.monthly_reset.start()

    def cog_unload(self):
        self.check_submissions.cancel()
        self.monthly_reset.cancel()

    def _calculate_points(self, rating: int, first_attempt: bool) -> int:
        """
        Formula:
        Base: 10 points for rating 800
        Scaling: +5 points for every +100 rating
        Bonus: +5 points if solved on first attempt
        """
        if rating < 800:
            base_points = 5 
        else:
            base_points = 10 + ((rating - 800) // 100) * 5
        
        bonus = 5 if first_attempt else 0
        return base_points + bonus

    @tasks.loop(minutes=10)
    async def check_submissions(self):
        """Monitor Codeforces rating changes and solve counts for points"""
        for guild in self.bot.guilds:
            try:
                users = cf_common.user_db.get_handles_for_guild(guild.id)
                for user_id, handle in users:
                    query = "SELECT last_submission_id, current_month_points FROM gamification_points WHERE user_id = ? AND guild_id = ?"
                    res = cf_common.user_db._fetchone(query, (str(user_id), str(guild.id)))
                    
                    if not res:
                        cf_common.user_db.conn.execute(
                            "INSERT INTO gamification_points (user_id, guild_id, current_month_points, last_submission_id) VALUES (?, ?, 1500, 0)",
                            (str(user_id), str(guild.id))
                        )
                        cf_common.user_db.conn.commit()
                        last_id, current_points = 0, 1500
                    else:
                        last_id, current_points = res.last_submission_id, res.current_month_points

                    try:
                        submissions = await cf.user.status(handle=handle, count=20)
                    except Exception:
                        continue

                    new_points = 0
                    max_sub_id = last_id
                    submissions.sort(key=lambda x: x.id)

                    for sub in submissions:
                        if sub.id <= last_id:
                            continue
                        
                        max_sub_id = max(max_sub_id, sub.id)

                        if sub.verdict == 'OK':
                            all_subs = await cf.user.status(handle=handle, count=100)
                            wa_before = any(s.problem.contestId == sub.problem.contestId and 
                                           s.problem.index == sub.problem.index and 
                                           s.verdict != 'OK' and s.creationTimeSeconds < sub.creationTimeSeconds 
                                           for s in all_subs)
                            
                            first_attempt = not wa_before
                            rating = sub.problem.rating or 800
                            pts = self._calculate_points(rating, first_attempt)
                            new_points += pts
                    
                    if new_points > 0 or max_sub_id > last_id:
                        query = "UPDATE gamification_points SET current_month_points = current_month_points + ?, last_submission_id = ? WHERE user_id = ? AND guild_id = ?"
                        cf_common.user_db.conn.execute(query, (new_points, max_sub_id, str(user_id), str(guild.id)))
                        cf_common.user_db.conn.commit()

            except Exception as e:
                self.logger.error(f"Error in check_submissions: {e}")

    @tasks.loop(time=datetime.time(hour=10, minute=0, tzinfo=pytz.UTC)) # 12:00 PM Cairo
    async def monthly_reset(self):
        """Reset all users to 1500 points on the 1st of every month"""
        now = datetime.datetime.now(pytz.UTC)
        if now.day != 1:
            return
        
        self.logger.info(f"Performing monthly points reset for {now.strftime('%B %Y')}...")
        try:
            cf_common.user_db.conn.execute("UPDATE gamification_points SET current_month_points = 1500")
            cf_common.user_db.conn.commit()
            
            for guild in self.bot.guilds:
                query = "SELECT channel_id FROM automation_settings_v2 WHERE guild_id = ? AND setting_type = 'master'"
                res = cf_common.user_db._fetchone(query, (str(guild.id),))
                if res and res.channel_id:
                    channel = guild.get_channel(int(res.channel_id))
                    if channel:
                        embed = discord_common.embed_alert("🌙 **New Month Has Started!**\nAll points have been reset to **1500**. Good luck to everyone!")
                        await channel.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Error during monthly reset: {e}")

    @commands.command(brief='Check your current gamification points')
    async def points(self, ctx, member: discord.Member = None):
        """Show your total points for this month."""
        member = member or ctx.author
        query = "SELECT current_month_points FROM gamification_points WHERE user_id = ? AND guild_id = ?"
        res = cf_common.user_db._fetchone(query, (str(member.id), str(ctx.guild.id)))
        
        pts = res.current_month_points if res else 1500
        
        embed = discord_common.embed_success(f"**{member.display_name}** has **{pts}** points this month!")
        if member.avatar: embed.set_thumbnail(url=member.avatar.url)
        await ctx.send(embed=embed)

    @check_submissions.before_loop
    @monthly_reset.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    async def cog_command_error(self, ctx, error):
        self.logger.error(f'Scoring cog error: {error}')

async def setup(bot):
    await bot.add_cog(Scoring(bot))
