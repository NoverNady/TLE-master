import discord
from discord.ext import commands, tasks
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List

from tle import constants
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common

logger = logging.getLogger(__name__)

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # tasks disabled as they are non-functional or replaced by automation.py
        # self.update_scores_loop.start()
        # self.weekly_report_task.start()
        # self.monthly_report_task.start()
        pass

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        """Sets up the server with necessary roles and channels."""
        status_msg = await ctx.send("Starting server setup...")
        guild = ctx.guild
        
        # 1. Create Codeforces Roles
        ranks = [
            "Newbie", "Pupil", "Specialist", "Expert", "Candidate Master", 
            "Master", "International Master", "Grandmaster", "International Grandmaster", "Legendary Grandmaster"
        ]
        colors = [
            0x808080, 0x008000, 0x03a89e, 0x0000ff, 0xaa00aa, 
            0xff8c00, 0xf57500, 0xff3030, 0xff0000, 0xcc0000
        ]
        
        for rank, color in zip(ranks, colors):
            if not discord.utils.get(guild.roles, name=rank):
                await guild.create_role(name=rank, color=discord.Color(color), hover=True)
        
        await ctx.send("✅ Codeforces Roles Created.")

        # 2. Create Local Ranks
        local_ranks = ["Bronze", "Silver", "Gold", "Platinum", "Diamond"]
        local_colors = [0xcd7f32, 0xc0c0c0, 0xffd700, 0xe5e4e2, 0xb9f2ff]
        
        for rank, color in zip(local_ranks, local_colors):
            if not discord.utils.get(guild.roles, name=rank):
                await guild.create_role(name=rank, color=discord.Color(color))
        
        await ctx.send("✅ Local Ranks Created.")

        # 3. Create Group Roles (G1 to G20)
        for i in range(1, 21):
            role_name = f"G{i}"
            if not discord.utils.get(guild.roles, name=role_name):
                await guild.create_role(name=role_name)
        
        await ctx.send("✅ Group Roles (G1-G20) Created.")
        await status_msg.edit(content="Server setup complete! 🚀")

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    async def debug_status(self, ctx):
        """Checks status of Cogs, API, and Background Tasks."""
        embed = discord.Embed(title="🕵️ Debug Status", color=discord.Color.dark_grey())
        
        # Cog Status
        cogs = [c for c in self.bot.cogs]
        embed.add_field(name="Loaded Cogs", value=", ".join(cogs) or "None", inline=False)
        
        # API Check
        try:
            start = datetime.now()
            await cf.contest.list(gym=False)
            latency = (datetime.now() - start).total_seconds() * 1000
            api_status = f"✅ Online ({latency:.0f}ms)"
        except Exception as e:
            api_status = f"❌ Error: {str(e)}"
        embed.add_field(name="Codeforces API", value=api_status, inline=True)
        
        # Task Status
        tasks_status = []
        tasks_status.append(f"Score Update: {'Running' if self.update_scores_loop.is_running() else 'Stopped'}")
        tasks_status.append(f"Weekly Report: {'Running' if self.weekly_report_task.is_running() else 'Stopped'}")
        embed.add_field(name="Background Tasks", value="\n".join(tasks_status), inline=False)

        await ctx.send(embed=embed)

    @tasks.loop(minutes=30)
    async def update_scores_loop(self):
        """Checks for new submissions and updates points."""
        logger.info("Starting score update loop...")
        try:
            # This is a simplified logic. In production, we'd need to iterate over all users
            # efficiently or hook into a submission feed. 
            # For now, we assume we want to track recent subs for active users.
            
            # 1. Get all linked users
            # active_users = cf_common.user_db.get_all_handles() # Pseudo-code
            pass 
            # Implementation details: fetch submissions for users, check against last_solved_count, add points
            # For each new problem:
            # - +10 pts
            # - +15 pts if first submission
            # cf_common.user_db.update_user_points(user_id, weekly_delta=10, monthly_delta=10, total_delta=10)
            
        except Exception as e:
            logger.error(f"Error in update_scores_loop: {e}")

    @tasks.loop(hours=168) # Weekly (needs better scheduling logic with @tasks.loop(time=...))
    async def weekly_report_task(self):
        # Implementation for weekly reports
        pass

    @tasks.loop(hours=720) # Monthly
    async def monthly_report_task(self):
        # Implementation for monthly reports
        pass

    @commands.Cog.listener()
    async def on_duel_complete(self, winner_id, loser_id, delta):
        # Hook for duel completion to add bonus points
        # Assuming we emit a custom event or call this method from the Duel cog
        bonus = 20
        cf_common.user_db.update_user_points(winner_id, weekly_delta=bonus, monthly_delta=bonus, total_delta=bonus)
        # Maybe notify the user
        
async def setup(bot):
    await bot.add_cog(Mentorship(bot))
