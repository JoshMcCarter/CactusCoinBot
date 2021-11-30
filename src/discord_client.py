import discord
import config
import commands
import views
import logging
import sys
import spellchecker
import atexit
import signal
import datetime

logging.basicConfig(stream=sys.stderr, level=config.getAttribute('logLevel'))

userCommands = {
    '!help': 'Usage: `!help` \n Outputs this list of commands.',
    '!verifycoin': 'Usage: `!verifycoin [user1] [user2] [user3]` \n Updates the user\'s role with their current amount or the default starting amount of coin.',
    '!give': 'Usage: `!give [user] [amount]` \n Gives coin to a specific user, no strings attached.',
    '!bet': 'Usage: `!bet [user] [amount] [reason]` \n Starts a bet instance with another member, follow the button prompts to complete the bet.',
    '!rankings': 'Usage: `!rankings` \n Outputs power rankings for the server.'
}

adminCommands = {
    '!adminhelp': 'Usage: `!adminhelp` \n Outputs this list of commands.',
    '!adminadjust': 'Usage: `!adminadjust [user] [amount]` \n Adds/subtracts coin from user\'s wallet.',
    '!clear': 'Usage: `!clear [user]` \n Clears a user\'s wallet of all coin.',
    '!reset': 'Usage: `!reset [user]` \n Resets a user\'s wallet to the default starting amount',
    '!balance': 'Usage: `!balance [user]` \n Outputs a user\'s wallet amount stored in the database.'
}

class Client(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def on_message(self, message: discord.Message):
        # we do not want the bot to reply to itself or message in other channels
        if message.author.id == self.user.id or message.channel.name != config.getAttribute('channelName'):
            return

        guild = message.channel.guild
        if message.content.startswith('!help'):
            embed = discord.Embed(title='Cactus Coin Bot Commands', color=discord.Color.dark_green())
            for key in userCommands.keys():
                embed.add_field(name=key, value=userCommands[key], inline=False)
            await message.channel.send(embed=embed)

        elif message.content.startswith('!adminhelp') and commands.is_admin(message.author):
            embed = discord.Embed(title='Cactus Coin Bot Admin Commands', color=discord.Color.orange())
            for key in adminCommands.keys():
                embed.add_field(name=key, value=adminCommands[key], inline=False)
            await message.channel.send(embed=embed)

        elif message.content.startswith('!hello'):
            await message.reply('Hello!')

        elif message.content.startswith('!sadge'):
            await message.channel.send('<:sadge:763188455248887819>')

        elif 'deez' in message.content:
            await message.reply('Deez nuts')

        elif message.content.startswith('!verifycoin'):
            if message.mentions:
                for member in message.mentions:
                    await commands.verify_coin(guild, member)
                await message.reply('Verified coin for: ' + ', '.join([mention.display_name for mention in message.mentions]))
            else:
                await message.reply('No mentions found. Follow the format: !verifycoin @user1 @user2 ...')

        elif message.content.startswith('!adminadjust') and commands.is_admin(message.author):
            messageContent = message.content.split()
            print(messageContent)
            if message.mentions and len(messageContent) == 3 and messageContent[2].lstrip('-').isnumeric():
                recieving_member = message.mentions[0]
                amount = int(messageContent[2])
                await commands.add_coin(guild, recieving_member, amount)
            else:
                await message.reply('Error parsing. Follow the format: !adminadjust @user ####')

        elif message.content.startswith('!clear') and commands.is_admin(message.author):
            if message.mentions:
                recieving_member = message.mentions[0]
                amount = commands.get_coin(recieving_member.id)
                await commands.add_coin(guild, recieving_member, -(amount - 1000))
                await commands.update_role(guild, recieving_member, config.getAttribute('defaultCoin'))
            else:
                await message.reply('Error parsing. Follow the format: !clear @user')

        elif message.content.startswith('!balance') and commands.is_admin(message.author):
            if message.mentions:
                recieving_member = message.mentions[0]
                balance = commands.get_coin(recieving_member.id)
                if balance:
                    await message.reply(f'{recieving_member.display_name}\'s balance: {str(balance)}.')
                else:
                    await message.reply(f'{recieving_member.display_name} has no balance.')
            else:
                await message.reply('Error parsing. Follow the format: !balance @user')

        elif message.content.startswith('!rankings'):
            filePath = await commands.compute_rankings(message.guild)
            file = discord.File(f'../tmp/power-rankings-{datetime.date.today().strftime("%m-%d-%Y")}.png')
            await message.channel.send('Here are the current power rankings:', file=file)

        elif message.content.startswith('!give'):
            messageContent = message.content.split()
            if message.mentions and len(messageContent) == 3 and messageContent[2].lstrip('-').isnumeric():
                recieving_member = message.mentions[0]
                amount = int(messageContent[2])
                if recieving_member.id == message.author.id:
                    await message.reply('Are you stupid or something?')
                elif amount > 0:
                    await commands.add_coin(guild, recieving_member, amount)
                    await commands.add_coin(guild, message.author, -amount )
                elif amount < 0:
                    await message.reply('Nice try <:shanechamp:910353567603384340>')
            else:
                await message.reply('Error parsing. Follow the format: !give @user ####')

        elif message.content.startswith('!bet'):
            messageContent = message.content.split(sep=None, maxsplit=3)
            if message.mentions and len(messageContent) == 4 and messageContent[2].lstrip('-').isnumeric():
                recieving_member = message.mentions[0]
                amount = int(messageContent[2])
                if recieving_member.id == message.author.id:
                    await message.reply('Are you stupid or something?')
                if amount < 0:
                    await message.reply('Nice try <:shanechamp:910353567603384340>')
                elif amount > 0:
                    # Have the challenged member confirm the bet
                    view = views.ConfirmBet(recieving_member.id)
                    betMessage = await message.channel.send(f'{recieving_member.mention} do you accept the bet?',
                                                            view=view)
                    # Wait for the View to stop listening for input...
                    await view.wait()
                    if view.value is None:
                        # if the bet message times out
                        await betMessage.delete()
                    elif not view.value:
                        await betMessage.edit(f'{recieving_member.display_name} has declined the bet.', view=None)
                    else:
                        betResultView = views.DecideBetOutcome(message.author, recieving_member)
                        await betMessage.edit(
                            recieving_member.display_name + ' has accepted the bet. After the bet is over, pick a winner below:',
                            view=betResultView)
                        await betResultView.wait()
                        if betResultView.winner is None:
                            await betMessage.edit('Something went wrong or the bet timed out.', view=None)
                        else:
                            winner = message.author if message.author.id == betResultView.winner else recieving_member
                            loser = message.author if message.author.id != betResultView.winner else recieving_member
                            await betMessage.edit(
                                f'{winner.display_name} won the ${str(amount)} bet against {loser.display_name} for "{messageContent[3]}"!',
                                view=None)
                            await commands.add_coin(guild, winner, amount)
                            await commands.add_coin(guild, loser, -amount )

            else:
                await message.reply('Error parsing. Follow the format: !bet @user #### reason here')

        # Can't parse command, reply best guess
        elif message.content.startswith('!'):
            command = message.content.split()[0]
            spellcheck = spellchecker.SpellChecker(language=None, case_sensitive=True)
            spellcheck.word_frequency.load_words(userCommands.keys())
            correction = spellcheck.correction(command)
            if correction != command:
                await message.reply(f'Invalid command, did you mean `{correction}`?  Try `!help` for valid commands.')
            else:
                await message.reply('Invalid command. Try `!help` for valid commands.')

intents = discord.Intents.default()
intents.members = True
client = Client(intents=intents)
client.run(config.getAttribute('token'))


def handle_exit():
    logging.info('Closing client down...')
    client.close()

atexit.register(handle_exit)
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)