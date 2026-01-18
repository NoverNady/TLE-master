import argparse
import asyncio
import distutils.util
import logging
import os
import discord
from logging.handlers import TimedRotatingFileHandler
from os import environ
from pathlib import Path

from os import environ
import firebase_admin
from firebase_admin import credentials
from firebase_admin import storage

STORAGE_BUCKET = str(environ.get('STORAGE_BUCKET'))
bucket = None
if STORAGE_BUCKET!='None':
    cred = credentials.Certificate('firebase-admin.json')
    firebase_admin.initialize_app(cred, {
        'storageBucket': STORAGE_BUCKET
    })
    bucket = storage.bucket()


# Set backend to Agg before importing pyplot or seaborn to avoid crashes on headless servers
import matplotlib
matplotlib.use('Agg')
import seaborn as sns
from discord.ext import commands
from matplotlib import pyplot as plt

from tle import constants
from tle.util import codeforces_common as cf_common
from tle.util import discord_common, font_downloader
from tle.util import clist_api


def setup():
    # Make required directories.
    for path in constants.ALL_DIRS:
        os.makedirs(path, exist_ok=True)
    
    # Update the user.db file from firebase
    if bucket!=None:
        try:
            blob = bucket.blob('tle.db')
            blob.download_to_filename(constants.USER_DB_FILE_PATH)
        except:
            # File is not present in Firebase Storage
            pass

    # logging to console and file on daily interval
    logging.basicConfig(format='{asctime}:{levelname}:{name}:{message}', style='{',
                        datefmt='%d-%m-%Y %H:%M:%S', level=logging.INFO,
                        handlers=[logging.StreamHandler(),
                                  TimedRotatingFileHandler(constants.LOG_FILE_PATH, when='D',
                                                           backupCount=3, utc=True)])

    # matplotlib and seaborn
    plt.rcParams['figure.figsize'] = 7.0, 3.5
    sns.set()
    options = {
        'axes.edgecolor': '#A0A0C5',
        'axes.spines.top': False,
        'axes.spines.right': False,
    }
    sns.set_style('darkgrid', options)

    # Download fonts if necessary
    font_downloader.maybe_download()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--nodb', action='store_true')
    args = parser.parse_args()

    token = environ.get('BOT_TOKEN')
    if not token:
        logging.error('Token required')
        return

    allow_self_register = environ.get('ALLOW_DUEL_SELF_REGISTER')
    if allow_self_register:
        constants.ALLOW_DUEL_SELF_REGISTER = bool(distutils.util.strtobool(allow_self_register))

    setup()
    
    # CRITICAL FIX: Initialize database BEFORE creating bot
    # This prevents AttributeError when ban_check tries to access user_db
    logging.info('Initializing database and cache...')
    await cf_common.initialize(args.nodb)
    logging.info('Database initialization complete')
    
    # Discord.py 2.0+ intents - explicitly enable required intents
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True  # Required for reading message content

    class TLEBot(commands.Bot):
        async def setup_hook(self):
            # Discord.py 2.0+ uses async cog loading
            cogs = [file.stem for file in Path('tle', 'cogs').glob('*.py')]
            for extension in cogs:
                try:
                    await self.load_extension(f'tle.cogs.{extension}')
                    logging.info(f'Loaded cog: {extension}')
                except Exception as e:
                    logging.error(f'Failed to load cog {extension}: {e}')
            logging.info(f'Cogs loaded: {", ".join(self.cogs)}')

    bot = TLEBot(command_prefix=commands.when_mentioned_or(';'), intents=intents)

    def no_dm_check(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage('Private messages not permitted.')
        return True
    
    def ban_check(ctx):
        # Database is now guaranteed to be initialized
        banned = cf_common.user_db.get_banned_user(ctx.author.id)
        if banned is None:
            return True
        return False

    # Restrict bot usage to inside guild channels only.
    bot.add_check(no_dm_check)
    bot.add_check(ban_check)

    # Cache contests on ready
    @discord_common.on_ready_event_once(bot)
    async def init():
        clist_api.cache()
        asyncio.create_task(discord_common.presence(bot))

    bot.add_listener(discord_common.bot_error_handler, name='on_command_error')
    
    # Start the bot
    await bot.start(token)


if __name__ == '__main__':
    # Use asyncio.run() for proper async entry point (Python 3.7+)
    asyncio.run(main())

