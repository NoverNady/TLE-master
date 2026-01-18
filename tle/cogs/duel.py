import random
import datetime
import discord
import asyncio
import itertools
import json

from discord.ext import commands
from collections import defaultdict, namedtuple
from matplotlib import pyplot as plt

from tle import constants
from tle.util.db.user_db_conn import Duel, DuelType, Winner
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import paginator
from tle.util import discord_common
from tle.util import table
from tle.util import graph_common as gc

_DUEL_INVALIDATE_TIME = 2 * 60
_DUEL_EXPIRY_TIME = 5 * 60
_DUEL_RATING_DELTA = -400
_DUEL_OFFICIAL_CUTOFF = 3500
_DUEL_NO_DRAW_TIME = 10 * 60
_ELO_CONSTANT = 60

DuelRank = namedtuple(
    'Rank', 'low high title title_abbr color_graph color_embed')

DUEL_RANKS = (
    DuelRank(-10 ** 9, 1300, 'Newbie', 'N', '#CCCCCC', 0x808080),
    DuelRank(1300, 1400, 'Pupil', 'P', '#77FF77', 0x008000),
    DuelRank(1400, 1500, 'Specialist', 'S', '#77DDBB', 0x03a89e),
    DuelRank(1500, 1600, 'Expert', 'E', '#AAAAFF', 0x0000ff),
    DuelRank(1600, 1700, 'Candidate Master', 'CM', '#FF88FF', 0xaa00aa),
    DuelRank(1700, 1800, 'Master', 'M', '#FFCC88', 0xff8c00),
    DuelRank(1800, 1900, 'International Master', 'IM', '#FFBB55', 0xf57500),
    DuelRank(1900, 2000, 'Grandmaster', 'GM', '#FF7777', 0xff3030),
    DuelRank(2000, 2100, 'International Grandmaster',
             'IGM', '#FF3333', 0xff0000),
    DuelRank(2100, 10 ** 9, 'Legendary Grandmaster',
             'LGM', '#AA0000', 0xcc0000)
)

def rating2rank(rating):
    for rank in DUEL_RANKS:
        if rank.low <= rating < rank.high:
            return rank

class DuelCogError(commands.CommandError):
    pass

class Dueling(commands.Cog):
    """Advanced Multi-Problem Duel System"""
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()

    def _get_advanced_data(self, duel_id):
        query = 'SELECT problem_names, challenger_completed, challengee_completed FROM advanced_duel_data WHERE duel_id = ?'
        return cf_common.user_db._fetchone(query, (duel_id,))

    def _update_completion(self, duel_id, is_challenger):
        col = 'challenger_completed' if is_challenger else 'challengee_completed'
        query = f'UPDATE advanced_duel_data SET {col} = 1 WHERE duel_id = ?'
        cf_common.user_db.conn.execute(query, (duel_id,))
        cf_common.user_db.conn.commit()

    @commands.group(brief='Duel commands', invoke_without_command=True)
    async def duel(self, ctx):
        """Duel commands group."""
        await ctx.send_help(ctx.command)

    @duel.command(brief='Challenge to a multi-problem duel')
    async def challenge(self, ctx, opponent: discord.Member, rating: int = None):
        """Challenge another member to a coding duel (3-4 problems)."""
        challenger_id = ctx.author.id
        challengee_id = opponent.id

        await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author), '!' + str(opponent)))
        
        if cf_common.user_db.check_duel_challenge(challenger_id):
            raise DuelCogError(f'{ctx.author.mention}, you are already in a duel!')
        if cf_common.user_db.check_duel_challenge(challengee_id):
             raise DuelCogError(f'**{opponent.display_name}** is already in a duel!')

        userids = [challenger_id, challengee_id]
        handles = [cf_common.user_db.get_handle(uid, ctx.guild.id) for uid in userids]
        submissions = [await cf.user.status(handle=h) for h in handles]
        
        users = [cf_common.user_db.fetch_cf_user(h) for h in handles]
        lowest_rating = min(u.rating or 0 for u in users)
        suggested_rating = max(round(lowest_rating, -2) + _DUEL_RATING_DELTA, 800)
        rating = round(rating, -2) if rating else suggested_rating

        num_probs = random.choice([3, 4])
        solved = {sub.problem.name for subs in submissions for sub in subs}
        
        def get_probs_for_rating(r):
            return [p for p in cf_common.cache2.problem_cache.problems 
                    if p.rating == r and p.name not in solved and not cf_common.is_nonstandard_problem(p)]

        problems_to_use = []
        for r in [rating, rating + 100, rating - 100, rating + 200, rating - 200]:
            candidates = get_probs_for_rating(r)
            if candidates:
                random.shuffle(candidates)
                problems_to_use.extend(candidates[:2])
            if len(problems_to_use) >= num_probs:
                break
        
        problems_to_use = problems_to_use[:num_probs]
        if len(problems_to_use) < num_probs:
            raise DuelCogError("Could not find enough problems in this range.")

        problem_names = ",".join([p.name for p in problems_to_use])
        issue_time = datetime.datetime.now().timestamp()
        
        duel_id = cf_common.user_db.create_duel(challenger_id, challengee_id, issue_time, problems_to_use[0], DuelType.OFFICIAL)
        
        cf_common.user_db.conn.execute(
            'INSERT INTO advanced_duel_data (duel_id, problem_names) VALUES (?, ?)',
            (duel_id, problem_names)
        )
        cf_common.user_db.conn.commit()

        await ctx.send(f'{ctx.author.mention} challenged {opponent.mention} to a duel of {num_probs} problems! (Rating: {rating})')
        
        await asyncio.sleep(_DUEL_EXPIRY_TIME)
        if cf_common.user_db.cancel_duel(duel_id, Duel.EXPIRED):
            await ctx.send(f'Challenge request for **{opponent.display_name}** has expired.')

    @duel.command(brief='Accept a duel')
    async def accept(self, ctx):
        """Accept a pending duel challenge."""
        active = cf_common.user_db.check_duel_accept(ctx.author.id)
        if not active: raise DuelCogError("No pending challenge found.")
        
        duel_id, challenger_id, _ = active
        adv = self._get_advanced_data(duel_id)
        
        start_time = datetime.datetime.now().timestamp()
        cf_common.user_db.start_duel(duel_id, start_time)
        
        challenger = ctx.guild.get_member(challenger_id)
        embed = discord_common.embed_success(f"⚔️ Duel Started: {challenger.mention} vs {ctx.author.mention}")
        embed.add_field(name="Problems", value="\n".join([f"• {name}" for name in adv.problem_names.split(",")]), inline=False)
        embed.set_footer(text="Type ;duel complete when finished.")
        await ctx.send(embed=embed)

    @duel.command(brief='Mark your side as complete')
    async def complete(self, ctx):
        """Mark yourself as finished. Duel ends when both sides complete."""
        active = cf_common.user_db.check_duel_complete(ctx.author.id)
        if not active: raise DuelCogError("You are not currently in an active duel.")
        
        duel_id, challenger_id, challengee_id, start_time, _, _, _, _ = active
        
        is_challenger = ctx.author.id == challenger_id
        self._update_completion(duel_id, is_challenger)
        
        adv = self._get_advanced_data(duel_id)
        if not (adv.challenger_completed and adv.challengee_completed):
            await ctx.send(f"✅ {ctx.author.mention}, you have finished. Waiting for opponent...")
            return

        await ctx.send("🔄 Both sides finished. Calculating scores...")
        
        prob_names = adv.problem_names.split(",")
        handle_challenger = cf_common.user_db.get_handle(challenger_id, ctx.guild.id)
        handle_challengee = cf_common.user_db.get_handle(challengee_id, ctx.guild.id)
        
        subs_challenger = await cf.user.status(handle=handle_challenger)
        subs_challengee = await cf.user.status(handle=handle_challengee)
        
        def calc_user_score(subs, start_t):
            total = 0
            for name in prob_names:
                prob_subs = [s for s in subs if s.problem.name == name and s.creationTimeSeconds >= start_t]
                ok_subs = [s for s in prob_subs if s.verdict == 'OK']
                if ok_subs:
                    first_ok_time = min(s.creationTimeSeconds for s in ok_subs)
                    wa_count = len([s for s in prob_subs if s.verdict not in ['OK', 'TESTING', 'COMPILATION_ERROR'] 
                                   and s.creationTimeSeconds < first_ok_time])
                    total += max(0, 30 - (wa_count * 5))
            return total

        score_a = calc_user_score(subs_challenger, start_time)
        score_b = calc_user_score(subs_challengee, start_time)
        
        challenger = ctx.guild.get_member(challenger_id)
        challengee = ctx.guild.get_member(challengee_id)
        
        winner_id = None
        if score_a > score_b: 
            winner, loser = challenger, challengee
            win_score, lose_score = score_a, score_b
            win_status = Winner.CHALLENGER
        elif score_b > score_a:
            winner, loser = challengee, challenger
            win_score, lose_score = score_b, score_a
            win_status = Winner.CHALLENGEE
        else:
            winner, win_status = None, Winner.DRAW
        
        finish_time = datetime.datetime.now().timestamp()
        cf_common.user_db.conn.execute('UPDATE duel SET status = ?, finish_time = ?, winner = ? WHERE id = ?', 
                                     (Duel.COMPLETE, finish_time, win_status, duel_id))
        cf_common.user_db.conn.commit()

        if winner:
            diff = win_score - lose_score
            cf_common.user_db.conn.execute(
                "UPDATE gamification_points SET current_month_points = current_month_points + ? WHERE user_id = ? AND guild_id = ?",
                (win_score, str(winner.id), str(ctx.guild.id))
            )
            cf_common.user_db.conn.execute(
                "UPDATE gamification_points SET current_month_points = current_month_points - ? WHERE user_id = ? AND guild_id = ?",
                (diff, str(loser.id), str(ctx.guild.id))
            )
            cf_common.user_db.conn.commit()
            
            embed = discord_common.embed_success(f"🏆 **{winner.display_name}** won the duel!")
            embed.add_field(name="Final Results", value=f"{challenger.display_name}: **{score_a}**\n{challengee.display_name}: **{score_b}**")
            embed.add_field(name="Points Impact", value=f"**{winner.display_name}**: +{win_score}\n**{loser.display_name}**: -{diff}")
        else:
            embed = discord_common.embed_success(f"🤝 The duel ended in a Draw!")
            embed.add_field(name="Final Results", value=f"Both Players: **{score_a}**")
            if score_a > 0:
                cf_common.user_db.conn.execute(
                    "UPDATE gamification_points SET current_month_points = current_month_points + ? WHERE (user_id = ? OR user_id = ?) AND guild_id = ?",
                    (score_a, str(challenger_id), str(challengee_id), str(ctx.guild.id))
                )
                cf_common.user_db.conn.commit()
                embed.add_field(name="Points Impact", value=f"Both Players: +{score_a}")
            else:
                embed.add_field(name="Points Impact", value="No points awarded (No problems solved)")
        
        await ctx.send(embed=embed)

    @duel.command(brief='Show duel history')
    async def history(self, ctx, member: discord.Member = None):
        """Displays the duel history for the specified member."""
        member = member or ctx.author
        data = cf_common.user_db.get_duels(member.id)
        if not data:
            raise DuelCogError(f'{member.display_name} has no duel history.')
        
        def make_line(entry):
            id, start_time, finish_time, problem_name, challenger, challengee, winner = entry
            challenger_name = ctx.guild.get_member(int(challenger))
            challengee_name = ctx.guild.get_member(int(challengee))
            challenger_name = challenger_name.display_name if challenger_name else "Unknown"
            challengee_name = challengee_name.display_name if challengee_name else "Unknown"
            
            problem = cf_common.cache2.problem_cache.problem_by_name.get(problem_name)
            problem_str = f'[{problem_name}]({problem.url})' if problem else problem_name
            
            time_str = cf_common.days_ago(finish_time)
            
            if winner == Winner.DRAW:
                result = "🤝 Draw"
            elif (winner == Winner.CHALLENGER and member.id == challenger) or \
                 (winner == Winner.CHALLENGEE and member.id == challengee):
                result = "✅ Won"
            else:
                result = "❌ Lost"
            
            return f"**{result}** vs {challengee_name if member.id == challenger else challenger_name} | {problem_str} | {time_str}"

        def make_page(chunk):
            embed = discord_common.embed_success(f"Duel History for {member.display_name}")
            for entry in chunk:
                embed.add_field(name=f"Duel #{entry.id}", value=make_line(entry), inline=False)
            return None, embed

        pages = [make_page(chunk) for chunk in paginator.chunkify(data, 5)]
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=5 * 60, set_pagenum_footers=True)

    @duel.command(brief='Withdraw, Decline or Give Up')
    async def cancel(self, ctx):
        """Cancel a pending challenge or withdraw from an ongoing duel."""
        res_w = cf_common.user_db.check_duel_withdraw(ctx.author.id)
        res_d = cf_common.user_db.check_duel_decline(ctx.author.id)
        ongoing = cf_common.user_db.check_duel_complete(ctx.author.id)
        
        if res_w:
            cf_common.user_db.cancel_duel(res_w[0], Duel.WITHDRAWN)
            await ctx.send("Challenge withdrawn.")
        elif res_d:
            cf_common.user_db.cancel_duel(res_d[0], Duel.DECLINED)
            await ctx.send("Challenge declined.")
        elif ongoing:
            await ctx.send(f"{ctx.author.mention}, if you wish to finish the duel early, please type `;duel complete`. You will only get points for problems currently solved.")
        else:
            raise DuelCogError("No active duel or pending challenge.")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, DuelCogError):
            await ctx.send(embed=discord_common.embed_alert(error))

async def setup(bot):
    await bot.add_cog(Dueling(bot))
