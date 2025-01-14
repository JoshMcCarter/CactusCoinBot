from random import randint
import discord
import config
import sql_client as sql
import logging
from io import BytesIO
from PIL import Image, ImageDraw
import os
from typing import List
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import datetime
from math import atan, exp
import numpy as np
import random

if not os.path.exists('../tmp'):
    os.makedirs('../tmp')

# Matplotlib styling
plt.style.use('dark_background')
for param in ['text.color', 'axes.labelcolor', 'xtick.color', 'ytick.color']:
    plt.rcParams[param] = '0.9'  # very light grey
for param in ['figure.facecolor', 'axes.facecolor', 'savefig.facecolor']:
    plt.rcParams[param] = '#212946'  # bluish dark grey
plt.rcParams['font.family'] = 'Tahoma'
plt.rcParams['font.size'] = 16

icon_size = (44, 44)
icon_mask = Image.new('L', (128, 128))
mask_draw = ImageDraw.Draw(icon_mask)
mask_draw.ellipse((0, 0, 128, 128), fill=255)


# Checks admin status for a member for specific admin only functionality.
def is_admin(member: discord.Member):
    roleNames = [role.name for role in member.roles if 'CactusCoinDev' in role.name or 'President' in role.name or 'Vice President' in role.name]
    if roleNames:
        return True
    return False


def is_dev(member: discord.Member):
    roleNames = [role.name for role in member.roles if 'CactusCoinDev' in role.name]
    if roleNames:
        return True
    return False


# Creates a cactus coin role that denotes the amount of coin a member has.
async def create_role(guild: discord.Guild, amount: int):
    # avoid duplicating roles whenever possible
    prefix = config.getAttribute('rolePrefix', 'Cactus Coin')
    newRoleName = f'{prefix}: ' + str(amount)
    existingRole = [role for role in guild.roles if role.name == newRoleName]
    if existingRole:
        return existingRole[0]
    return await guild.create_role(name=newRoleName, reason='Cactus Coin: New CC amount.', color=discord.Color.dark_gold())


# Removes the cactus coin role from the member's role and from the guild if necessary
async def remove_role(guild: discord.Guild, member: discord.Member):
    cactusRoles = [role for role in member.roles if 'Cactus Coin:' in role.name]
    if cactusRoles:
        cactusRole = cactusRoles[0]
        await member.remove_roles(cactusRole)
        # if the current user is the only one with the role or there are no users with the role
        await clear_old_roles(guild)


# Verifies the state of a user's role denoting their coin, creates it if it doesn't exist.
async def verify_coin(guild: discord.Guild, member: discord.Member, amount: int = config.getAttribute('defaultCoin')):
    # update coin for member who has cactus coin in database
    db_amount = get_coin(member.id)
    if db_amount:
        amount = db_amount
        logging.debug('Found coin for ' + member.display_name + ': ' + str(db_amount))
    else:
        logging.debug('No coin found for ' + member.display_name + ', defaulting to: ' + str(amount))
        update_coin(member.id, amount)

    roleNames = [role.name for role in member.roles if 'Cactus Coin:' in role.name]
    if not roleNames:
        role = await create_role(guild, amount)
        await member.add_roles(role, reason='Cactus Coin: Role updated for ' + member.name + ' to ' + str(amount))


# Deletes all old cactus coin roles
async def clear_old_roles(guild: discord.Guild):
    emptyRoles = [role for role in guild.roles if 'Cactus Coin:' in role.name and len(role.members) == 0]
    for role in emptyRoles:
        await role.delete(reason='Cactus Coin: Removing unused role.')


# Deletes old role and calls function to update new role displaying coin amount
async def update_role(guild: discord.Guild, member: discord.Member, amount: int):
    await remove_role(guild, member)
    role = await create_role(guild, amount)
    await member.add_roles(role, reason='Cactus Coin: Role updated for ' + member.name + ' to ' + str(amount))


# Adds a specified coin amount to a member's role and stores in the database
async def add_coin(guild: discord.Guild, member: discord.Member, amount: int, persist: bool=True):
    memberId = member.id
    current_coin = get_coin(memberId)
    current_coin += amount
    update_coin(memberId, current_coin)
    if persist:
        add_transaction(memberId, amount)
    await update_role(guild, member, current_coin)


# Gets outlier movements either positive or negative and outputs a chart of them
async def get_movements(guild: discord.Guild, timePeriod: str, isWins: bool):
    # TODO: FIX TIME PERIODS, GET START OF TIME THEN CONVERT TO UTC
    if timePeriod == 'week':
        startPeriod = datetime.datetime.now() - datetime.timedelta(days=datetime.datetime.now().weekday())
    elif timePeriod == 'month':
        startPeriod = datetime.datetime.today().replace(day=1)
    elif timePeriod == 'year':
        startPeriod = datetime.date(datetime.date.today().year, 1, 1)

    transactions = get_transactions(startPeriod)
    if not transactions:
        return None
    if isWins:
        transactions = [i for i in transactions if i[1] > 0]
    else:
        transactions = [i for i in transactions if i[1] < 0]
    numb_trans = min(len(transactions), 5)
    transactions = transactions[:numb_trans] if isWins else transactions[-numb_trans:]
    
    await graph_amounts(guild, transactions)
    plt.xlabel('Coin (¢)')

    if isWins:
        plt.title('Greatest Wins From the Past ' + timePeriod.capitalize(), fontweight='bold')
        filename = f'../tmp/wins-{timePeriod}.png'
    else:    
        plt.title('Greatest Losses From the Past ' + timePeriod.capitalize(), fontweight='bold')
        filename = f'../tmp/losses-{timePeriod}.png'
    plt.savefig(filename, bbox_inches='tight', pad_inches=.5)
    plt.close()
    return filename


# Computes power rankings for the server and outputs them in a bar graph in an image
async def compute_rankings(guild: discord.Guild):
    rankings = get_coin_rankings()
    await graph_amounts(guild, rankings)
    today = datetime.date.today().strftime("%m-%d-%Y")
    plt.title('Cactus Gang Power Rankings\n' + today, fontweight='bold')
    plt.xlabel('Coin (¢)')
    plt.savefig(f'../tmp/power-rankings-{today}.png', bbox_inches='tight', pad_inches=.5)
    plt.close()
    return f'../tmp/power-rankings-{today}.png'


# Generic function for graphing a nice looking bar chart of values for each member
# This function does not set plot title, axis titles, or close the plot
async def graph_amounts(guild: discord.Guild, data):
    # pull all images of ranking members from Discord
    memberIcons, memberNames, memberAmounts, memberColor = [], [], [], []
    storedIcons = os.listdir('../tmp')
    for memberid, amount in data:
        member = guild.get_member(memberid)
        if not member:
            return
        icon = member.display_avatar
        # check if we already have the file in tmp folder, if not grab it and save it.
        if f'{icon.key}-44px.png' not in storedIcons:
            img = Image.open(BytesIO(await icon.read()))
            img = img.resize((128, 128))
            img.save(f'../tmp/{icon.key}.png')
            img.putalpha(icon_mask)
            img = img.resize(icon_size)
            img.save(f'../tmp/{icon.key}-44px.png')
            img.close()

        memberIcons.append(f'../tmp/{icon.key}-44px.png')
        memberNames.append(member.display_name)
        memberAmounts.append(amount)
        # alternate bar color generation
        # im = img.resize((1, 1), Image.NEAREST).convert('RGB')
        # color = im.getpixel((0, 0))
        # normalize pixel values between 0 and 1
        memberC = member.color if member.color != discord.Color.default() or member.color != discord.Color.from_rgb(1, 1, 1) else discord.Color.blurple()
        color = (memberC.r, memberC.g, memberC.b)
        memberColor.append(tuple(t/255. for t in color))
    ax = plt.axes()
    ax.set_axisbelow(True)
    ax.yaxis.grid(color='.9', linestyle='dashed')
    ax.xaxis.grid(color='.9', linestyle='dashed')
    lab_x = [i for i in range(len(data))]
    height = .8
    plt.barh(lab_x, memberAmounts, height=height, color=memberColor)
    plt.yticks(lab_x, memberNames)

    # create a glowy effect on the plot by plotting different bars
    n_shades = 5
    diff_linewidth = .05
    alpha_value = 0.5 / n_shades
    for n in range(1, n_shades + 1):
        plt.barh(lab_x, memberAmounts,
                height=(height + (diff_linewidth * n)),
                alpha=alpha_value,
                color=memberColor)

    # add user icons to bar charts
    max_value = max(memberAmounts)
    for i, (value, icon) in enumerate(zip(memberAmounts, memberIcons)):
        offset_image(value, i, icon, max_value=max_value, ax=ax)


# Adds discord icons to bar chart
def offset_image(x, y, icon, max_value, ax):
    img = plt.imread(icon)
    im = OffsetImage(img, zoom=0.65)
    im.image.axes = ax
    x_offset = -25
    # if bar is too short to show icon
    if 0 <= x < max_value / 5:
        x = x + max_value // 8
    elif x < max_value / 5:
        x = 0
    ab = AnnotationBbox(im, (x, y), xybox=(x_offset, 0), frameon=False,
                        xycoords='data', boxcoords="offset points", pad=0)
    ax.add_artist(ab)


#dont know if you wanted this returns the index of the winning member in members
def get_winner(num_players,win_ang):
    sliceDegree = 360/num_players
    curr_degree = win_ang
    for i in range(num_players):
        if curr_degree < sliceDegree:
            return i
        curr_degree -= sliceDegree

# Generate wheel for bet as a gif
def generate_wheel(members: List[discord.Member]):
    canvas_size = 1000
    wheel_offset = 5
    bounding_box = [(wheel_offset, wheel_offset), (canvas_size - wheel_offset, canvas_size - wheel_offset)]
    sliceDegree = 360 / len(members)
    currSlice = 0
    wheelPath = '../tmp/wheel.png'
    # TODO: FIX WHEEL STYLE AND ADD TEXT
    wheel = Image.new('RGBA', (canvas_size, canvas_size), '#DDD')
    for member in members:
        wheelDraw = ImageDraw.Draw(wheel)
        wheelDraw.pieslice(bounding_box, start=currSlice, end=currSlice+sliceDegree, fill=member['color'], width=5, outline='black')
        currSlice += sliceDegree
    wheel.save('../tmp/wheel.png')

    win_ang = random.randint(0,360)

    #generate time mesh for acceleration function to operate on
    #set to be 7 "seconds" polled at .1 seconds found this gave enough
    #points to make a smoother gif
    time_mesh = [t for t in np.arange(0.0,7.0,0.1)]
    
    #starting set of rotations I found to look like someone is pulling a wheel back for 
    #a rather large spin. can be messed around with 
    start_animation = [0.0, -0.75, -1.5, -2.25, -3.0, -3.75, -4.5, -5.25]
    
    #start actual spin at the last part of the pullback
    #store all rotations of original image (in degrees) that create the gif
    rotations = [start_animation[7]]
    velocities = [0]

    #i picked e^2t for no real reason other than it makes the wheel get up to speed quick
    acceleration_func = lambda t: exp(2*t) if t <= 2.0 else 0

    #now calculate distance traveled in degrees from the original image for each point in the
    #time mesh using basic rotational dynamics
    for i in range(1,len(time_mesh)):
        t = time_mesh[i]
        a = acceleration_func(t)
        v = velocities[i-1] + a * t
        d = rotations[i-1] + v * t

        rotations.append(d)
        velocities.append(v)

    #reguardless of where we ended up, square up the last point with the original image so we can
    #position the wheel where the winning slice always hits the top
    win_ang_pos = rotations[len(rotations)-1] + (360 - (rotations[len(rotations)-1] % 360))
    rotations.append(win_ang_pos)

    #in order to hit the top of the circle, find the distance from the winning angle to 270(the top
    #of the circle). The minus 180 here is used to get the more gentle stop from the end_animation
    #array
    rotations.append(win_ang_pos + (270 - win_ang) - 180 if win_ang <= 270 else win_ang_pos + 360 - (win_ang - 270) - 180)
    end_animation = [45,45,25,20,20,10,5,2,1,1,1]
    curr = rotations[len(rotations)-1]
    for i in range(len(end_animation)):
        curr += end_animation[i]
        rotations.append(curr)

    #append the start animation to the front of the rotations array
    rotations = start_animation + rotations

    #make the gif
    wheelImgs = [wheel.rotate(-rotations[i], expand=False, fillcolor='#DDD') for i in range(len(rotations))]
    wheel.save('../tmp/out.gif', save_all=True, append_images=wheelImgs)
    return wheelPath


#############################################################
# SQL functions for updating DB state
#############################################################
def update_coin(memberid: int, amount: int):
    logging.debug('Updating coin for: ' + str(memberid) + ': ' + str(amount))
    cur = sql.connection.cursor()
    cur.execute("INSERT INTO AMOUNTS(id, coin) VALUES ('{0}', {1}) ON CONFLICT(id) DO UPDATE SET coin=excluded.coin".format(memberid, amount))
    sql.connection.commit()
    return amount


def get_coin(memberid: int):
    cur = sql.connection.cursor()
    amount = cur.execute("SELECT coin from AMOUNTS WHERE id IS '{0}'".format(memberid)).fetchall()
    if amount:
        return amount[0][0]
    return None


# Clears out all coin from a member's entry
def remove_coin(memberid: int):
    cur = sql.connection.cursor()
    cur.execute("DELETE FROM AMOUNTS WHERE id is '{0}'".format(memberid))
    sql.connection.commit()


# Adds a transaction entry for a specific member
def add_transaction(memberid: int, amount: int):
    cur = sql.connection.cursor()
    cur.execute("INSERT INTO TRANSACTIONS(date, id, coin) VALUES (?, ?, ?)", (datetime.datetime.utcnow(), memberid, amount))
    sql.connection.commit()


# Removes all transactions associated with a user
def remove_transactions(memberid: int):
    cur = sql.connection.cursor()
    cur.execute("DELETE FROM TRANSACTIONS WHERE id is '{0}'".format(memberid))
    sql.connection.commit()


# Gets rankings of coin amounts
def get_coin_rankings():
    cur = sql.connection.cursor()
    amounts = cur.execute("SELECT id, coin FROM AMOUNTS ORDER BY coin").fetchall()
    if amounts:
        return amounts
    return None


# Get all transactions between now and the given date, ordered from greatest to least.
def get_transactions(time: datetime):
    cur = sql.connection.cursor()
    transactions = cur.execute("SELECT id, coin FROM TRANSACTIONS WHERE date BETWEEN ? AND ? ORDER BY coin", (time, datetime.datetime.utcnow())).fetchall()
    if transactions:
        return transactions
    return None
