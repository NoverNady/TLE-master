import discord
from discord.ext import commands, tasks
import logging
import datetime
import pytz
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
    """Automated standings and leaderboard posts"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Create the table on startup
        self._create_automation_table()
        
        # Start the automated tasks
        self.weekly_standings_task.start()
        self.monthly_standings_task.start()

    def cog_unload(self):
        """Stop tasks when cog is unloaded"""
        self.weekly_standings_task.cancel()
        self.monthly_standings_task.cancel()

    def _get_automation_channel(self, guild_id: int) -> Optional[int]:
        """Get the configured automation channel for a guild"""
        # Store in database similar to reminder settings
        # For now, we'll use a simple in-memory dict (should be persisted to DB)
        query = '''
            SELECT channel_id FROM automation_settings WHERE guild_id = ?
        '''
        try:
            result = cf_common.user_db.conn.execute(query, (str(guild_id),)).fetchone()
            return int(result[0]) if result else None
        except Exception as e:
            self.logger.error(f"Error fetching automation channel: {e}")
            return None

    def _set_automation_channel(self, guild_id: int, channel_id: int):
        """Set the automation channel for a guild"""
        query = '''
            INSERT OR REPLACE INTO automation_settings (guild_id, channel_id)
            VALUES (?, ?)
        '''
        try:
            cf_common.user_db.conn.execute(query, (str(guild_id), str(channel_id)))
            cf_common.user_db.conn.commit()
            cf_common.user_db.update()
        except Exception as e:
            self.logger.error(f"Error setting automation channel: {e}")
            raise AutomationCogError("Failed to set automation channel")

    def _create_automation_table(self):
        """Create the automation_settings table if it doesn't exist"""
        query = '''
            CREATE TABLE IF NOT EXISTS automation_settings (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT
            )
        '''
        try:
            cf_common.user_db.conn.execute(query)
            cf_common.user_db.conn.commit()
        except Exception as e:
            self.logger.error(f"Error creating automation table: {e}")

    async def _get_top_users_by_rating(self, guild_id: int, limit: int = 10) -> List[tuple]:
        """Get top users by Codeforces rating for a guild"""
        try:
            users = cf_common.user_db.get_cf_users_for_guild(str(guild_id))
            # Filter out users without rating and sort by rating
            rated_users = [(user_id, user) for user_id, user in users if user and user.rating]
            rated_users.sort(key=lambda x: x[1].rating, reverse=True)
            return rated_users[:limit]
        except Exception as e:
            self.logger.error(f"Error fetching top users: {e}")
            return []

    async def _get_top_users_by_solved_count(self, guild_id: int, limit: int = 10) -> List[tuple]:
        """Get top users by number of problems solved"""
        try:
            users = cf_common.user_db.get_cf_users_for_guild(str(guild_id))
            user_solve_counts = []
            
            for user_id, user in users:
                if not user or not user.handle:
                    continue
                
                try:
                    # Fetch submissions for the user
                    submissions = await cf.user.status(handle=user.handle)
                    # Count unique solved problems
                    solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}
                    user_solve_counts.append((user_id, user, len(solved)))
                except Exception as e:
                    self.logger.warning(f"Error fetching submissions for {user.handle}: {e}")
                    continue
            
            # Sort by solve count
            user_solve_counts.sort(key=lambda x: x[2], reverse=True)
            return user_solve_counts[:limit]
        except Exception as e:
            self.logger.error(f"Error fetching users by solve count: {e}")
            return []

    def _create_standings_embed(self, title: str, users_data: List, guild: discord.Guild, 
                                mode: str = "rating") -> discord.Embed:
        """Create an embed for standings"""
        embed = discord.Embed(
            title=title,
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )
        
        if not users_data:
            embed.description = "No data available yet. Make sure users have linked their handles!"
            return embed

        # Medal emojis for top 3
        medals = ["🥇", "🥈", "🥉"]
        
        description_lines = []
        
        for idx, data in enumerate(users_data):
            rank = idx + 1
            medal = medals[idx] if idx < 3 else f"**{rank}.**"
            
            if mode == "rating":
                user_id, user = data
                member = guild.get_member(user_id)
                username = member.display_name if member else f"User {user_id}"
                handle = user.handle
                rating = user.rating or 0
                
                # Color code based on rating
                if rating >= 2400:
                    color = "🔴"
                elif rating >= 2100:
                    color = "🟠"
                elif rating >= 1900:
                    color = "🟣"
                elif rating >= 1600:
                    color = "🔵"
                elif rating >= 1400:
                    color = "🟢"
                elif rating >= 1200:
                    color = "🟢"
                else:
                    color = "⚪"
                
                line = f"{medal} {color} **{username}** ([{handle}](https://codeforces.com/profile/{handle})) - **{rating}**"
            else:  # solved count mode
                user_id, user, solve_count = data
                member = guild.get_member(user_id)
                username = member.display_name if member else f"User {user_id}"
                handle = user.handle
                
                line = f"{medal} **{username}** ([{handle}](https://codeforces.com/profile/{handle})) - **{solve_count}** problems"
            
            description_lines.append(line)
        
        embed.description = "\n".join(description_lines)
        embed.set_footer(text=f"Generated for {guild.name}")
        
        return embed

    @tasks.loop(time=datetime.time(hour=10, minute=0, tzinfo=pytz.UTC))  # Friday 12:00 PM Cairo time (10:00 UTC)
    async def weekly_standings_task(self):
        """Post weekly standings every Friday at 12:00 PM"""
        # Check if today is Friday (weekday 4)
        if datetime.datetime.now(pytz.UTC).weekday() != 4:
            return
        
        self.logger.info("Running weekly standings task...")
        
        for guild in self.bot.guilds:
            try:
                channel_id = self._get_automation_channel(guild.id)
                if not channel_id:
                    continue
                
                channel = guild.get_channel(channel_id)
                if not channel:
                    self.logger.warning(f"Channel {channel_id} not found in guild {guild.name}")
                    continue
                
                # Get top users by rating
                top_users = await self._get_top_users_by_rating(guild.id, limit=10)
                
                embed = self._create_standings_embed(
                    title="🏆 Weekly Standings - Top 10 by Rating",
                    users_data=top_users,
                    guild=guild,
                    mode="rating"
                )
                
                await channel.send(embed=embed)
                self.logger.info(f"Posted weekly standings to {guild.name}")
                
            except Exception as e:
                self.logger.error(f"Error posting weekly standings for {guild.name}: {e}")

    @weekly_standings_task.before_loop
    async def before_weekly_standings(self):
        """Wait until bot is ready before starting the task"""
        await self.bot.wait_until_ready()
        self._create_automation_table()

    @tasks.loop(time=datetime.time(hour=10, minute=0, tzinfo=pytz.UTC))  # 1st of month at 12:00 PM Cairo (10:00 UTC)
    async def monthly_standings_task(self):
        """Post monthly standings on the 1st of every month at 12:00 PM"""
        # Check if today is the 1st of the month
        if datetime.datetime.now(pytz.UTC).day != 1:
            return
        
        self.logger.info("Running monthly standings task...")
        
        for guild in self.bot.guilds:
            try:
                channel_id = self._get_automation_channel(guild.id)
                if not channel_id:
                    continue
                
                channel = guild.get_channel(channel_id)
                if not channel:
                    self.logger.warning(f"Channel {channel_id} not found in guild {guild.name}")
                    continue
                
                # Get top users by rating
                top_users = await self._get_top_users_by_rating(guild.id, limit=15)
                
                # Get current month name
                month_name = datetime.datetime.now().strftime("%B %Y")
                
                embed = self._create_standings_embed(
                    title=f"🏆 Monthly Standings - {month_name}",
                    users_data=top_users,
                    guild=guild,
                    mode="rating"
                )
                
                await channel.send(embed=embed)
                self.logger.info(f"Posted monthly standings to {guild.name}")
                
            except Exception as e:
                self.logger.error(f"Error posting monthly standings for {guild.name}: {e}")

    @monthly_standings_task.before_loop
    async def before_monthly_standings(self):
        """Wait until bot is ready before starting the task"""
        await self.bot.wait_until_ready()

    @commands.command(brief='Set automation channel for standings')
    @commands.has_permissions(administrator=True)
    async def setup_auto(self, ctx, channel: discord.TextChannel = None):
        """Set the channel where automated standings will be posted.
        
        Usage:
        ;setup_auto #channel-name
        ;setup_auto (uses current channel)
        """
        target_channel = channel or ctx.channel
        
        try:
            self._set_automation_channel(ctx.guild.id, target_channel.id)
            
            embed = discord_common.embed_success(
                f"Automation channel set to {target_channel.mention}\n\n"
                f"**Weekly Standings:** Every Friday at 12:00 PM\n"
                f"**Monthly Standings:** 1st of every month at 12:00 PM"
            )
            await ctx.send(embed=embed)
            
        except Exception as e:
            raise AutomationCogError(f"Failed to set automation channel: {e}")

    @commands.command(brief='Show automation settings')
    async def auto_settings(self, ctx):
        """Show current automation settings for this server"""
        channel_id = self._get_automation_channel(ctx.guild.id)
        
        embed = discord.Embed(
            title="⚙️ Automation Settings",
            color=discord.Color.blue()
        )
        
        if channel_id:
            channel = ctx.guild.get_channel(channel_id)
            channel_mention = channel.mention if channel else f"Channel ID: {channel_id} (not found)"
            embed.add_field(name="Automation Channel", value=channel_mention, inline=False)
        else:
            embed.add_field(name="Automation Channel", value="Not configured", inline=False)
        
        embed.add_field(name="Weekly Standings", value="Every Friday at 12:00 PM", inline=True)
        embed.add_field(name="Monthly Standings", value="1st of every month at 12:00 PM", inline=True)
        
        next_friday = datetime.datetime.now()
        days_ahead = 4 - next_friday.weekday()  # 4 = Friday
        if days_ahead <= 0:
            days_ahead += 7
        next_friday += datetime.timedelta(days=days_ahead)
        
        embed.add_field(
            name="Next Weekly Post",
            value=next_friday.strftime("%A, %B %d, %Y"),
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(brief='Manually trigger weekly standings', hidden=True)
    @commands.has_permissions(administrator=True)
    async def post_weekly(self, ctx):
        """Manually post weekly standings (for testing)"""
        channel_id = self._get_automation_channel(ctx.guild.id)
        
        if not channel_id:
            raise AutomationCogError("Automation channel not configured. Use `;setup_auto` first.")
        
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            raise AutomationCogError(f"Configured channel not found.")
        
        top_users = await self._get_top_users_by_rating(ctx.guild.id, limit=10)
        
        embed = self._create_standings_embed(
            title="🏆 Weekly Standings - Top 10 by Rating",
            users_data=top_users,
            guild=ctx.guild,
            mode="rating"
        )
        
        await channel.send(embed=embed)
        await ctx.send(f"✅ Posted weekly standings to {channel.mention}")

    @commands.command(brief='Manually trigger monthly standings', hidden=True)
    @commands.has_permissions(administrator=True)
    async def post_monthly(self, ctx):
        """Manually post monthly standings (for testing)"""
        channel_id = self._get_automation_channel(ctx.guild.id)
        
        if not channel_id:
            raise AutomationCogError("Automation channel not configured. Use `;setup_auto` first.")
        
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            raise AutomationCogError(f"Configured channel not found.")
        
        top_users = await self._get_top_users_by_rating(ctx.guild.id, limit=15)
        
        month_name = datetime.datetime.now().strftime("%B %Y")
        
        embed = self._create_standings_embed(
            title=f"🏆 Monthly Standings - {month_name}",
            users_data=top_users,
            guild=ctx.guild,
            mode="rating"
        )
        
        await channel.send(embed=embed)
        await ctx.send(f"✅ Posted monthly standings to {channel.mention}")

    async def cog_command_error(self, ctx, error):
        """Error handler for this cog"""
        if isinstance(error, AutomationCogError):
            await ctx.send(embed=discord_common.embed_alert(error))
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=discord_common.embed_alert("You need Administrator permissions to use this command."))


async def setup(bot):
    """Setup function to load the cog"""
    await bot.add_cog(Automation(bot))
